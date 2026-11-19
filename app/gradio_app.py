"""AsukaRVC-SVC fullstack server, hosted by Gradio + FastAPI.

Gradio serves the application (its bundled uvicorn/FastAPI stack) and mounts a
small "Voice Lab" Blocks app at /manage.  The main studio is a plain HTML/CSS/JS
frontend served as static files, talking to the JSON API below.

Run:
    .venv-rvc\\Scripts\\python.exe app\\gradio_app.py
    # or
    uvicorn app.gradio_app:app --host 127.0.0.1 --port 8777

Docs used:
    https://www.gradio.app/docs/gradio/mount_gradio_app
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
import webbrowser
from pathlib import Path

import gradio as gr
import uvicorn
from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
sys.path.insert(0, str(ROOT))

from app import server as base  # noqa: E402  (shared jobs / projects / voices)
from app.engine import project as projmod, rvc as rvcmod  # noqa: E402
from app.engine.phonemes import G2P  # noqa: E402
from app.engine.synth import note_phoneme_map  # noqa: E402

WEB = APP_DIR / "web"
RENDERS = ROOT / "data" / "renders"
SAFE_FILE = base.SAFE_FILE
SAFE_ID = base.SAFE_ID
VERSION = base.VERSION

_g2p = base._g2p

# Windows sometimes maps .js to text/plain in the registry, which breaks
# module scripts; make sure the static studio is served with correct types
# even when the app is started through `uvicorn app.gradio_app:app`.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

# Probe the RVC environment in the background regardless of how we are started,
# so /api/state stops saying "probing" and the UI badge becomes truthful.
threading.Thread(target=base.warm_rvc, name="rvc-probe", daemon=True).start()

app = FastAPI(title="AsukaRVC-SVC — RVC Singing Studio", version=VERSION)


class NoCacheStatic(StaticFiles):
    """Serve the hand-written studio assets with revalidation, so edits show up
    on the next reload instead of being served from the browser's heuristics."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStatic(directory=str(WEB)), name="static")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def state_payload() -> dict:
    with base.RVC_LOCK:
        rvc_status = dict(base.RVC_STATUS)
    return {
        "version": VERSION,
        "rvc": rvc_status,
        "voices": rvcmod.list_voices(),
        "projects": base.list_projects(),
        "defaultProject": projmod.default_project(),
        "lexicon": _g2p.lexicon_size,
        "engine": {
            "name": "Asuka formant singer",
            "sampleRate": 16000,
            "rvcInput": "16 kHz mono WAV",
            "server": "gradio+fastapi",
        },
    }


def _audio(name: str, request: Request, download: bool = False):
    name = os.path.basename(name)
    if not SAFE_FILE.match(name) or not name.lower().endswith(".wav"):
        return JSONResponse({"error": "Bad file"}, status_code=400)
    path = RENDERS / name
    if not path.is_file():
        return JSONResponse({"error": "Not found"}, status_code=404)
    data = path.read_bytes()
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    range_header = request.headers.get("range")
    if range_header and "bytes=" in range_header:
        m = re.match(r"bytes=(\d*)-(\d*)", range_header)
        if m:
            start = int(m.group(1) or 0)
            end = int(m.group(2)) if m.group(2) else len(data) - 1
            end = min(end, len(data) - 1)
            start = max(0, min(start, len(data) - 1))
            chunk = data[start : end + 1]
            headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            headers["Content-Length"] = str(len(chunk))
            return Response(chunk, status_code=206, media_type="audio/wav", headers=headers)
    headers["Content-Length"] = str(len(data))
    return Response(data, media_type="audio/wav", headers=headers)


# --------------------------------------------------------------------------- #
# static studio
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(str(WEB / "index.html"), media_type="text/html")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# API (mirrors the classic stdlib server)
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "time": int(time.time())}


@app.get("/api/state")
def api_state():
    return state_payload()


@app.get("/api/voices")
def api_voices():
    return {"voices": rvcmod.list_voices()}


@app.post("/api/voices")
async def api_voice_upload(
    pth: UploadFile = File(...),
    index: UploadFile | None = File(None),
    name: str = Form(""),
    pitch: int = Form(0),
    sid: int = Form(0),
    color: str = Form("#d81f2a"),
):
    pth_bytes = await pth.read()
    if not (pth.filename or "").lower().endswith(".pth"):
        return JSONResponse({"error": "Voice model must be a .pth file"}, status_code=400)
    idx_bytes = None
    if index is not None and index.filename:
        idx_bytes = await index.read()
    try:
        voice = rvcmod.install_voice(
            name=name or Path(pth.filename or "voice.pth").stem,
            pth_bytes=pth_bytes,
            pth_name=pth.filename or "voice.pth",
            index_bytes=idx_bytes,
            index_name=index.filename if index else None,
            pitch=int(pitch or 0),
            sid=int(sid or 0),
            color=color or "#d81f2a",
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Could not install voice: {exc}"}, status_code=400)
    return {"voice": voice, "voices": rvcmod.list_voices()}


@app.delete("/api/voices")
def api_voice_delete(id: str = ""):
    return {"ok": rvcmod.delete_voice(id)}


@app.get("/api/projects")
def api_projects(id: str = ""):
    if id:
        data = base.load_project(id)
        if data is None:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        return {"id": id, "project": data}
    return {"projects": base.list_projects()}


@app.post("/api/projects")
def api_project_save(payload: dict = Body(...)):
    try:
        return base.save_project(payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.delete("/api/projects")
def api_project_delete(id: str = ""):
    if not SAFE_ID.match(id or ""):
        return JSONResponse({"error": "Bad project id"}, status_code=400)
    target = base.PROJECTS / f"{id}.json"
    if target.is_file():
        target.unlink()
    return {"ok": True}


@app.get("/api/demo")
def api_demo():
    return {"project": projmod.default_project()}


@app.get("/api/jobs")
def api_jobs():
    with base.JOBS_LOCK:
        jobs = [base.job_public(base.JOBS[j]) for j in reversed(base.JOB_ORDER[-20:]) if j in base.JOBS]
    return {"jobs": jobs}


@app.get("/api/job")
def api_job(id: str = ""):
    with base.JOBS_LOCK:
        job = base.JOBS.get(id)
        if job:
            return base.job_public(job)
    return JSONResponse({"error": "Job not found"}, status_code=404)


@app.post("/api/render")
def api_render(payload: dict = Body(...)):
    try:
        return base.start_render(payload)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/api/cancel")
def api_cancel(payload: dict = Body(...)):
    job_id = payload.get("id", "")
    with base.JOBS_LOCK:
        job = base.JOBS.get(job_id)
    if job:
        job["cancel"].set()
        base.set_job(job_id, message="Cancelling…")
    return {"ok": True}


@app.post("/api/rvc/check")
def api_rvc_check():
    threading.Thread(target=base.warm_rvc, daemon=True).start()
    return {"ok": True, "probing": True}


@app.get("/api/rvc")
def api_rvc():
    with base.RVC_LOCK:
        return dict(base.RVC_STATUS)


@app.get("/api/g2p")
def api_g2p(text: str = "", midi: int = 60, dur: float = 1.0, bpm: float = 120.0):
    phones = _g2p.text_to_phones(text)
    words = [
        {"word": token, "phones": _g2p.word_to_phones(token)}
        for token in re.split(r"\s+", text.strip())
        if token
    ]
    payload = {"text": text, "phones": phones, "words": words}
    try:
        note = {"midi": midi, "start": 0, "dur": dur, "lyric": text or "la", "velocity": 0.8}
        payload["note"] = note_phoneme_map([note], bpm, _g2p)[0]
    except Exception:  # noqa: BLE001
        pass
    return payload


@app.get("/api/audio/{name}")
def api_audio(name: str, request: Request):
    return _audio(name, request, download=False)


@app.get("/api/download/{name}")
def api_download(name: str, request: Request):
    return _audio(name, request, download=True)


# --------------------------------------------------------------------------- #
# Gradio "Voice Lab" — mounted at /manage
# --------------------------------------------------------------------------- #
def _human_size(size: int) -> str:
    mb = size / 1048576
    if mb >= 1:
        return f"{mb:.0f} MB"
    return f"{max(1, round(size / 1024))} KB"


def voice_rows():
    rows = []
    for v in rvcmod.list_voices():
        rows.append([
            v["name"],
            _human_size(v["size"]),
            "yes" if v.get("index") else "no",
            v.get("pitch", 0),
            v["id"],
        ])
    return rows


def rvc_status_md():
    with base.RVC_LOCK:
        r = dict(base.RVC_STATUS)
    if r.get("probing"):
        return "### Engine status\n`probing…` — the first check loads torch, this takes a few seconds."
    if r.get("available"):
        return (
            "### Engine status\n"
            f"**RVC ready** · torch `{r.get('torch')}` · device `{r.get('device', 'cpu')}`  \n"
            f"RMVPE: `{'ok' if r.get('rmvpe') else 'missing'}` · "
            f"ContentVec: `{'ok' if r.get('contentvec') else 'missing'}`"
        )
    return f"### Engine status\n**RVC unavailable** — {r.get('reason', 'unknown')}"


def refresh_lab():
    return rvc_status_md(), voice_rows()


def lab_install(pth_path, idx_path, name, pitch, sid):
    if not pth_path:
        return "Choose a `.pth` model first.", voice_rows()
    try:
        pth = Path(pth_path)
        idx = Path(idx_path) if idx_path else None
        voice = rvcmod.install_voice(
            name=(name or pth.stem).strip(),
            pth_bytes=pth.read_bytes(),
            pth_name=pth.name,
            index_bytes=idx.read_bytes() if idx else None,
            index_name=idx.name if idx else None,
            pitch=int(pitch or 0),
            sid=int(sid or 0),
        )
        return f"Installed **{voice['name']}** — select it in the studio.", voice_rows()
    except Exception as exc:  # noqa: BLE001
        return f"Upload failed: `{exc}`", voice_rows()


def lab_delete(voice_id):
    if not voice_id:
        return "Pick a voice id (last column of the table).", voice_rows()
    ok = rvcmod.delete_voice(str(voice_id).strip())
    return ("Deleted." if ok else "Voice not found."), voice_rows()


with gr.Blocks(
    title="AsukaRVC-SVC · Voice Lab",
    theme=gr.themes.Base(
        primary_hue="red",
        secondary_hue="orange",
        neutral_hue="stone",
        radius_size=gr.themes.sizes.radius_sm,
    ),
    css="""
    .gradio-container { max-width: 980px !important; margin: auto; }
    footer { display: none !important; }
    """,
) as admin:
    gr.Markdown(
        "# AsukaRVC-SVC · Voice Lab\n"
        "Manage the RVC engine and voicebanks used by the studio. "
        "[← Back to the piano roll](/)\n\n"
        "The studio UI is plain **HTML / CSS / JavaScript**, served by this Gradio host. "
        "The engine renders a 16 kHz carrier vocal, then RVC converts it with the selected voice."
    )
    status_md = gr.Markdown(rvc_status_md())
    voice_table = gr.Dataframe(
        headers=["Voice", "Size", "Index", "Pitch", "ID"],
        value=voice_rows(),
        interactive=False,
        wrap=True,
    )
    with gr.Row():
        refresh_btn = gr.Button("Refresh")
        check_btn = gr.Button("Re-check RVC engine")

    gr.Markdown("## Add a voicebank")
    with gr.Row():
        pth_file = gr.File(label="RVC model (.pth)", file_types=[".pth"], type="filepath")
        idx_file = gr.File(label="FAISS index (optional)", file_types=[".index"], type="filepath")
    with gr.Row():
        name_box = gr.Textbox(label="Display name", placeholder="e.g. Luna")
        pitch_box = gr.Number(label="Pitch shift (semitones)", value=0, precision=0)
        sid_box = gr.Number(label="Speaker ID", value=0, precision=0)
    install_btn = gr.Button("Install voicebank", variant="primary")
    upload_msg = gr.Markdown()

    gr.Markdown("## Remove a voicebank")
    with gr.Row():
        del_id = gr.Textbox(label="Voice ID (from the table)")
        del_btn = gr.Button("Delete", variant="stop")
    del_msg = gr.Markdown()

    refresh_btn.click(refresh_lab, outputs=[status_md, voice_table])
    check_btn.click(lambda: (base.warm_rvc(), refresh_lab())[1], outputs=[status_md, voice_table])
    install_btn.click(
        lab_install,
        inputs=[pth_file, idx_file, name_box, pitch_box, sid_box],
        outputs=[upload_msg, voice_table],
    )
    del_btn.click(lab_delete, inputs=[del_id], outputs=[del_msg, voice_table])

    # The RVC probe runs in the background at startup, so poll the status line
    # until it settles instead of leaving "probing…" on screen forever.
    status_timer = gr.Timer(3)
    status_timer.tick(rvc_status_md, outputs=status_md)

# Mount the Gradio app on the same FastAPI application.
app = gr.mount_gradio_app(
    app,
    admin,
    path="/manage",
    max_file_size="2gb",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="AsukaRVC-SVC - Gradio fullstack server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARVC_PORT") or os.environ.get("VOXFORGE_PORT") or 8777))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    print()
    print("  AsukaRVC-SVC - RVC Singing Studio (Gradio host)")
    print("  ----------------------------------------------")
    print(f"  Studio   {url}")
    print(f"  Voices   {url}manage")
    print(f"  Project  {ROOT}")
    print("  Stop with Ctrl+C")
    print()
    if not args.no_browser:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  bye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
