"""AsukaRVC-SVC server — stdlib HTTP API + static UI.

Run:  python app/server.py            (opens the browser)
      python app/server.py --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT))

from app.engine import effects, project as projmod, render as rendermod, rvc as rvcmod  # noqa: E402
from app.engine.phonemes import G2P  # noqa: E402
from app.engine.synth import note_phoneme_map  # noqa: E402

WEB = APP_DIR / "web"
DATA = ROOT / "data"
PROJECTS = DATA / "projects"
RENDERS = DATA / "renders"
VERSION = "1.0.0"

for folder in (DATA, PROJECTS, RENDERS, ROOT / "models"):
    folder.mkdir(parents=True, exist_ok=True)

SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

_g2p = G2P(str(ROOT / "assets" / "cmudict.dict"))

RVC_STATUS = {"available": False, "reason": "probing RVC environment…", "probing": True}
RVC_LOCK = threading.Lock()

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.RLock()
JOB_ORDER: list[str] = []


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def job_public(job: dict) -> dict:
    with JOBS_LOCK:
        out = {k: v for k, v in job.items() if k != "cancel"}
        out["log"] = list(job.get("log") or [])
    return out


def set_job(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job.update(fields)
            job["updated"] = time.time()


def append_job_log(job_id: str, line: str) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        log = job.setdefault("log", [])
        log.append(str(line)[:500])
        if len(log) > 120:
            del log[:-120]


def start_render(body: dict) -> dict:
    project = projmod.normalise(body.get("project") or {})
    options = body.get("options") or {}
    job_id = f"{projmod.slugify(project['name']).lower()}-{uuid.uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "status": "queued",
        "progress": 0.0,
        "message": "Queued",
        "log": [],
        "result": None,
        "error": None,
        "created": time.time(),
        "updated": time.time(),
        "cancel": threading.Event(),
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
        JOB_ORDER.append(job_id)
        while len(JOB_ORDER) > 40:
            stale = JOB_ORDER.pop(0)
            if stale not in JOBS or JOBS[stale]["status"] in ("done", "error", "cancelled"):
                JOBS.pop(stale, None)

    def progress(value: float) -> None:
        pct = round(max(0.0, min(1.0, value)) * 100, 1)
        with JOBS_LOCK:
            if job["status"] == "queued":
                job["status"] = "running"
            job["progress"] = pct
            job["message"] = f"Rendering… {pct:.0f}%"

    def log(line: str) -> None:
        append_job_log(job_id, line)

    def worker() -> None:
        set_job(job_id, status="running", message="Starting")
        try:
            options["jobId"] = job_id
            result = rendermod.render(
                project,
                options,
                progress=progress,
                log=log,
                cancel=job["cancel"],
            )
            set_job(
                job_id,
                status="done",
                progress=100.0,
                message="Done",
                result=result,
                error=None,
            )
        except rendermod.Cancelled:
            set_job(job_id, status="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001
            append_job_log(job_id, traceback.format_exc()[-2000:])
            set_job(job_id, status="error", message="Render failed", error=str(exc))

    threading.Thread(target=worker, name=f"render-{job_id}", daemon=True).start()
    with JOBS_LOCK:
        return {k: v for k, v in job.items() if k != "cancel"}


def warm_rvc() -> None:
    global RVC_STATUS
    try:
        status = rvcmod.check_rvc(force=True)
        status["probing"] = False
        with RVC_LOCK:
            RVC_STATUS = status
    except Exception as exc:  # noqa: BLE001
        with RVC_LOCK:
            RVC_STATUS = {
                "available": False,
                "reason": f"RVC probe failed: {exc}",
                "probing": False,
            }


def list_projects() -> list[dict]:
    out = []
    for path in sorted(PROJECTS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            notes = sum(len(t.get("notes") or []) for t in (data.get("tracks") or []))
            out.append({
                "id": path.stem,
                "name": data.get("name") or path.stem,
                "bpm": data.get("bpm"),
                "tracks": len(data.get("tracks") or []),
                "notes": notes,
                "updated": int(path.stat().st_mtime),
            })
        except (OSError, ValueError):
            continue
    return out


def load_project(pid: str) -> dict | None:
    if not SAFE_ID.match(pid or ""):
        return None
    path = PROJECTS / f"{pid}.json"
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_project(payload: dict) -> dict:
    project = projmod.normalise(payload.get("project") or payload)
    pid = str(payload.get("id") or project.get("id") or "").strip()
    if not SAFE_ID.match(pid):
        pid = f"{projmod.slugify(project['name']).lower()}-{uuid.uuid4().hex[:6]}"
    project["id"] = pid
    path = PROJECTS / f"{pid}.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(project, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return {"id": pid, "project": project}


def parse_multipart(body: bytes, content_type: str):
    m = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type or "")
    if not m:
        raise ValueError("Missing multipart boundary")
    boundary = (m.group(1) or m.group(2)).strip().encode("utf-8")
    delimiter = b"--" + boundary
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    for chunk in body.split(delimiter):
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        if chunk.endswith(b"\r\n"):
            chunk = chunk[:-2]
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        raw_headers, data = chunk.split(b"\r\n\r\n", 1)
        headers = {}
        for line in raw_headers.split(b"\r\n"):
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.decode("latin-1").strip().lower()] = v.decode("latin-1").strip()
        disp = headers.get("content-disposition", "")
        name_m = re.search(r'name="([^"]*)"', disp)
        file_m = re.search(r'filename="([^"]*)"', disp)
        if not name_m:
            continue
        field = name_m.group(1)
        if file_m:
            files[field] = (os.path.basename(file_m.group(1)), data)
        else:
            fields[field] = data.decode("utf-8", errors="replace")
    return fields, files


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AsukaRVC-SVC/" + VERSION

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, fmt, *args):  # noqa: D401
        if os.environ.get("ARVC_VERBOSE"):
            sys.stderr.write("[http] " + (fmt % args) + "\n")

    def _send(self, status: int, body: bytes, content_type: str,
              extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, obj, status: int = 200) -> None:
        self._send(status, json_bytes(obj), "application/json; charset=utf-8")

    def error_json(self, message: str, status: int = 400, **extra) -> None:
        payload = {"error": message}
        payload.update(extra)
        self.send_json(payload, status)

    def read_body(self, limit: int = 1_600_000_000) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > limit:
            raise ValueError("Request body too large")
        remaining = length
        chunks = []
        while remaining > 0:
            chunk = self.rfile.read(min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def json_body(self, limit: int = 32_000_000):
        raw = self.read_body(limit)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def query(self) -> dict[str, str]:
        qs = parse_qs(urlparse(self.path).query)
        return {k: v[-1] for k, v in qs.items() if v}

    # -- routing ----------------------------------------------------------- #
    def do_HEAD(self):
        self.do_GET()

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain", {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/" or path == "/index.html":
                return self.serve_static("index.html")
            if path.startswith("/static/"):
                return self.serve_static(path[len("/static/"):])
            if path.startswith("/api/audio/"):
                return self.serve_audio(unquote(path[len("/api/audio/"):]), download=False)
            if path.startswith("/api/download/"):
                return self.serve_audio(unquote(path[len("/api/download/"):]), download=True)
            if path == "/api/health":
                return self.send_json({"ok": True, "version": VERSION, "time": int(time.time())})
            if path == "/api/state":
                return self.send_json(self.state())
            if path == "/api/voices":
                return self.send_json({"voices": rvcmod.list_voices()})
            if path == "/api/projects":
                q = self.query()
                if q.get("id"):
                    data = load_project(q["id"])
                    if data is None:
                        return self.error_json("Project not found", 404)
                    return self.send_json({"id": q["id"], "project": data})
                return self.send_json({"projects": list_projects()})
            if path == "/api/demo":
                return self.send_json({"project": projmod.default_project()})
            if path == "/api/jobs":
                with JOBS_LOCK:
                    jobs = [job_public(JOBS[j]) for j in reversed(JOB_ORDER[-20:]) if j in JOBS]
                return self.send_json({"jobs": jobs})
            if path == "/api/job":
                q = self.query()
                with JOBS_LOCK:
                    job = JOBS.get(q.get("id", ""))
                if not job:
                    return self.error_json("Job not found", 404)
                return self.send_json(job_public(job))
            if path == "/api/g2p":
                return self.g2p_lookup()
            if path == "/api/rvc":
                with RVC_LOCK:
                    status = dict(RVC_STATUS)
                return self.send_json(status)
            return self.error_json("Not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.error_json(f"Server error: {exc}", 500)

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            if path == "/api/render":
                body = self.json_body()
                return self.send_json(start_render(body))
            if path == "/api/projects":
                body = self.json_body()
                saved = save_project(body)
                return self.send_json(saved)
            if path == "/api/voices":
                return self.upload_voice()
            if path == "/api/cancel":
                body = self.json_body()
                job_id = body.get("id", "")
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                if job:
                    job["cancel"].set()
                    set_job(job_id, message="Cancelling…")
                return self.send_json({"ok": True})
            if path == "/api/rvc/check":
                threading.Thread(target=warm_rvc, daemon=True).start()
                return self.send_json({"ok": True, "probing": True})
            if path == "/api/rvc/download":
                return self.send_json({"ok": False, "error": "Use tools/setup_rvc.ps1"})
            return self.error_json("Not found", 404)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.error_json(f"Server error: {exc}", 500)

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path
            q = self.query()
            if path == "/api/voices":
                ok = rvcmod.delete_voice(q.get("id", ""))
                return self.send_json({"ok": ok})
            if path == "/api/projects":
                pid = q.get("id", "")
                if not SAFE_ID.match(pid):
                    return self.error_json("Bad project id", 400)
                target = PROJECTS / f"{pid}.json"
                if target.is_file():
                    target.unlink()
                return self.send_json({"ok": True})
            return self.error_json("Not found", 404)
        except Exception as exc:  # noqa: BLE001
            return self.error_json(f"Server error: {exc}", 500)

    # -- implementations --------------------------------------------------- #
    def state(self) -> dict:
        with RVC_LOCK:
            rvc_status = dict(RVC_STATUS)
        return {
            "version": VERSION,
            "rvc": rvc_status,
            "voices": rvcmod.list_voices(),
            "projects": list_projects(),
            "defaultProject": projmod.default_project(),
            "lexicon": _g2p.lexicon_size,
            "engine": {
                "name": "Asuka formant singer",
                "sampleRate": 16000,
                "rvcInput": "16 kHz mono WAV",
                "server": "stdlib",
            },
        }

    def g2p_lookup(self):
        q = self.query()
        text = q.get("text", "")
        phones = _g2p.text_to_phones(text)
        words = []
        for token in re.split(r"\s+", text.strip()):
            if token:
                words.append({"word": token, "phones": _g2p.word_to_phones(token)})
        payload = {"text": text, "phones": phones, "words": words}
        try:
            midi = int(q.get("midi", "60"))
            dur = float(q.get("dur", "1"))
            bpm = float(q.get("bpm", "120"))
            note = {"midi": midi, "start": 0, "dur": dur, "lyric": text or "la",
                    "velocity": 0.8}
            payload["note"] = note_phoneme_map([note], bpm, _g2p)[0]
        except (TypeError, ValueError):
            pass
        return self.send_json(payload)

    def upload_voice(self):
        content_type = self.headers.get("Content-Type", "")
        body = self.read_body()
        fields, files = parse_multipart(body, content_type)
        if "pth" not in files:
            return self.error_json("Attach a .pth voice model", 400)
        pth_name, pth_bytes = files["pth"]
        if not pth_name.lower().endswith(".pth"):
            return self.error_json("Voice model must be a .pth file", 400)
        index_name, index_bytes = (None, None)
        if "index" in files and files["index"][1]:
            index_name, index_bytes = files["index"]

        def as_int(key, default=0):
            try:
                return int(float(fields.get(key, default)))
            except (TypeError, ValueError):
                return default

        try:
            voice = rvcmod.install_voice(
                name=fields.get("name") or Path(pth_name).stem,
                pth_bytes=pth_bytes,
                pth_name=pth_name,
                index_bytes=index_bytes,
                index_name=index_name,
                pitch=as_int("pitch", 0),
                sid=as_int("sid", 0),
                color=fields.get("color") or "#d81f2a",
            )
        except Exception as exc:  # noqa: BLE001
            return self.error_json(f"Could not install voice: {exc}", 400)
        return self.send_json({"voice": voice, "voices": rvcmod.list_voices()})

    def serve_static(self, rel: str):
        rel = rel.replace("\\", "/")
        if ".." in rel or rel.startswith("/"):
            return self.error_json("Bad path", 400)
        target = (WEB / rel).resolve()
        try:
            target.relative_to(WEB.resolve())
        except ValueError:
            return self.error_json("Bad path", 400)
        if not target.is_file():
            return self.error_json("Not found", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if target.suffix in (".js", ".mjs"):
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix in (".html", ".htm"):
            ctype = "text/html; charset=utf-8"
        body = target.read_bytes()
        self._send(200, body, ctype)

    def serve_audio(self, name: str, download: bool):
        name = os.path.basename(name)
        if not SAFE_FILE.match(name) or not name.lower().endswith(".wav"):
            return self.error_json("Bad file", 400)
        path = RENDERS / name
        if not path.is_file():
            return self.error_json("Not found", 404)
        size = path.stat().st_size
        ctype = "audio/wav"
        extra = {"Accept-Ranges": "bytes"}
        if download:
            extra["Content-Disposition"] = f'attachment; filename="{name}"'
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
                status = 206
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(262144, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description="AsukaRVC-SVC — RVC singing studio")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARVC_PORT") or os.environ.get("VOXFORGE_PORT") or 8777))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    threading.Thread(target=warm_rvc, name="rvc-probe", daemon=True).start()

    port = args.port
    last_error = None
    for attempt in range(20):
        try:
            httpd = ThreadingHTTPServer((args.host, port), Handler)
            httpd.daemon_threads = True
            break
        except OSError as exc:
            last_error = exc
            port += 1
    else:
        print(f"Could not bind a port: {last_error}")
        return 1

    url = f"http://{args.host}:{port}/"
    print()
    print("  AsukaRVC-SVC - RVC Singing Studio")
    print("  ------------------------------------")
    print(f"  UI      {url}")
    print(f"  Project {ROOT}")
    print(f"  Engine  16 kHz formant singer -> RVC")
    print("  Stop with Ctrl+C")
    print()
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  bye")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
