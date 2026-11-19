"""Bridge between the AsukaRVC-SVC app and the RVC inference stack.

The UI/server run on plain Python.  RVC (torch, hubert, faiss...) lives in an
isolated 3.12 virtualenv (.venv-rvc) and is driven through a subprocess worker.
If the venv is missing the app simply keeps the DSP singer and tells the user
how to enable RVC.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MODELS = ROOT / "models"
RENDERS = DATA / "renders"
WORKER = Path(__file__).resolve().with_name("rvc_worker.py")
STATUS_CACHE = DATA / "rvc_status.json"

_RVC_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


# --------------------------------------------------------------------------- #
# Environment discovery
# --------------------------------------------------------------------------- #
def rvc_python() -> str | None:
    env = os.environ.get("RVC_PYTHON")
    if env and os.path.isfile(env):
        return env
    for candidate in (
        ROOT / ".venv-rvc" / "Scripts" / "python.exe",
        ROOT / ".venv-rvc" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def _cached_status() -> dict | None:
    try:
        with open(STATUS_CACHE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if time.time() - float(data.get("checked", 0)) < 3600:
            return data
    except (OSError, ValueError, TypeError):
        return None
    return None


def check_rvc(force: bool = False) -> dict:
    """Return {'available': bool, 'reason': str, 'torch': str, 'python': str}."""
    if not force:
        cached = _cached_status()
        if cached is not None:
            return cached

    py = rvc_python()
    status = {
        "available": False,
        "reason": "RVC environment not installed",
        "torch": None,
        "python": py,
        "checked": time.time(),
    }
    if not py:
        status["reason"] = "RVC venv missing — run tools\\setup_rvc.ps1"
    else:
        probe = (
            "import sys,torch,librosa,faiss,soundfile;"
            "print(torch.__version__);"
            "print('cuda' if torch.cuda.is_available() else 'cpu')"
        )
        try:
            res = subprocess.run(
                [py, "-c", probe],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(ROOT),
            )
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                status["available"] = True
                status["torch"] = lines[0] if lines else "unknown"
                status["device"] = lines[1] if len(lines) > 1 else "cpu"
                status["reason"] = "ready"
            else:
                err = (res.stderr or res.stdout or "").strip().splitlines()
                status["reason"] = "RVC env broken: " + (err[-1] if err else "import failed")
        except subprocess.TimeoutExpired:
            status["reason"] = "RVC environment probe timed out"
        except OSError as exc:
            status["reason"] = f"Could not start RVC python: {exc}"

    # predictor availability
    status["rmvpe"] = (ROOT / "programs" / "rvc" / "models" / "predictors" / "rmvpe.pt").is_file()
    status["contentvec"] = (
        ROOT / "programs" / "rvc" / "models" / "embedders" / "contentvec" / "pytorch_model.bin"
    ).is_file()

    try:
        DATA.mkdir(parents=True, exist_ok=True)
        with open(STATUS_CACHE, "w", encoding="utf-8") as fh:
            json.dump(status, fh)
    except OSError:
        pass
    return status


# --------------------------------------------------------------------------- #
# Voicebank library
# --------------------------------------------------------------------------- #
def _voice_id(path: Path) -> str:
    rel = path.relative_to(MODELS).as_posix().lower()
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]


def _meta_path() -> Path:
    return DATA / "voices.json"


def _load_meta() -> dict:
    try:
        with open(_meta_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_meta(meta: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = _meta_path().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
    os.replace(tmp, _meta_path())


def _read_model_info(pth: Path) -> dict:
    """Read a few facts from the .pth header without torch."""
    info = {"sample_rate": None, "version": None, "speakers": None, "f0": None}
    try:
        import struct

        with open(pth, "rb") as fh:
            header = fh.read(8)
            if header[:2] != b"PK":
                return info
            fh.seek(0)
            raw = fh.read(min(pth.stat().st_size, 4_000_000))
        # ZIP central directory is at the end; the pickled archive name often
        # contains "config" hints, so read the archive comments instead.
        return info
    except Exception:
        return info


def list_voices() -> list[dict]:
    MODELS.mkdir(parents=True, exist_ok=True)
    meta = _load_meta()
    voices = []
    for pth in sorted(MODELS.rglob("*.pth")):
        if pth.name.startswith("."):
            continue
        vid = _voice_id(pth)
        rel = pth.relative_to(MODELS).as_posix()
        m = meta.get(rel, {})
        index = m.get("index") or ""
        if index:
            idx_path = MODELS / index
            index_path = str(idx_path) if idx_path.is_file() else ""
        else:
            index_path = ""
            if not index_path:
                same = pth.with_suffix(".index")
                if same.is_file():
                    index_path = str(same)
        if not index_path:
            siblings = list(pth.parent.glob("*.index"))
            if len(siblings) == 1:
                index_path = str(siblings[0])
        label = m.get("name") or pth.stem.replace("_", " ").strip() or pth.name
        voices.append(
            {
                "id": vid,
                "name": label,
                "file": rel,
                "path": str(pth),
                "index": index_path,
                "indexName": Path(index_path).name if index_path else "",
                "size": pth.stat().st_size,
                "pitch": m.get("pitch", 0),
                "sid": m.get("sid", 0),
                "color": m.get("color", "#d81f2a"),
                "created": m.get("created"),
            }
        )
    return voices


def get_voice(voice_id: str | None) -> dict | None:
    if not voice_id:
        return None
    for voice in list_voices():
        if voice["id"] == voice_id:
            return voice
    return None


def _safe_filename(name: str) -> str:
    name = os.path.basename(name or "voice.pth")
    name = _RVC_SAFE.sub("_", name)
    return name or "voice.pth"


def install_voice(name: str, pth_bytes: bytes, pth_name: str,
                  index_bytes: bytes | None = None, index_name: str | None = None,
                  pitch: int = 0, sid: int = 0, color: str = "#d81f2a") -> dict:
    """Store a voicebank in models/<safe name>/ and return its descriptor."""
    label = (name or Path(pth_name).stem).strip()
    folder = _RVC_SAFE.sub("_", label).strip(" .") or "voice"
    target_dir = MODELS / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    pth_path = target_dir / _safe_filename(pth_name)
    pth_path.write_bytes(pth_bytes)

    index_rel = ""
    if index_bytes:
        idx_name = _safe_filename(index_name or (pth_path.stem + ".index"))
        if not idx_name.lower().endswith(".index"):
            idx_name += ".index"
        idx_path = target_dir / idx_name
        idx_path.write_bytes(index_bytes)
        index_rel = idx_path.relative_to(MODELS).as_posix()

    meta = _load_meta()
    rel = pth_path.relative_to(MODELS).as_posix()
    meta[rel] = {
        "name": label,
        "index": index_rel,
        "pitch": int(pitch),
        "sid": int(sid),
        "color": color,
        "created": int(time.time()),
    }
    _save_meta(meta)
    vid = _voice_id(pth_path)
    for voice in list_voices():
        if voice["id"] == vid:
            return voice
    raise RuntimeError("Voice was saved but could not be indexed")


def delete_voice(voice_id: str) -> bool:
    voice = get_voice(voice_id)
    if not voice:
        return False
    pth = Path(voice["path"])
    rel = pth.relative_to(MODELS).as_posix()
    meta = _load_meta()
    meta.pop(rel, None)
    _save_meta(meta)
    for target in (pth, Path(voice["index"]) if voice.get("index") else None):
        if target is None:
            continue
        try:
            target.unlink()
        except OSError:
            pass
    # remove empty folder
    try:
        folder = pth.parent
        if folder != MODELS and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    return True


# --------------------------------------------------------------------------- #
# Conversion
# --------------------------------------------------------------------------- #
def convert(
    source_wav: str,
    output_wav: str,
    voice: dict,
    *,
    pitch: int = 0,
    f0_method: str = "rmvpe",
    index_rate: float = 0.75,
    protect: float = 0.33,
    volume_envelope: float = 0.9,
    sid: int = 0,
    log=None,
    timeout: float = 1800.0,
) -> dict:
    """Run RVC conversion. Returns {'ok', 'wav', 'log', 'f0_method'}."""
    status = check_rvc()
    if not status["available"]:
        return {"ok": False, "error": status["reason"], "log": status["reason"]}

    py = status["python"]
    f0 = f0_method or "rmvpe"
    if f0.startswith("rmvpe") and not status.get("rmvpe"):
        f0 = "crepe"
    if f0 == "fcpe" and not (ROOT / "programs" / "rvc" / "models" / "predictors" / "fcpe.pt").is_file():
        f0 = "crepe"

    cfg = {
        "root": str(ROOT),
        "input": str(Path(source_wav).resolve()),
        "output": str(Path(output_wav).resolve()),
        "model": voice["path"],
        "index": voice.get("index") or "",
        "pitch": int(pitch),
        "f0_method": f0,
        "index_rate": float(index_rate),
        "protect": float(protect),
        "volume_envelope": float(volume_envelope),
        "sid": int(sid),
        "export_format": "WAV",
    }
    RENDERS.mkdir(parents=True, exist_ok=True)
    cfg_path = RENDERS / (Path(output_wav).stem + "_rvc.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    lines: list[str] = []
    proc = subprocess.Popen(
        [py, str(WORKER), str(cfg_path)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    started = time.time()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            lines.append(line)
            if len(lines) > 400:
                lines = lines[-400:]
            if log:
                log(line)
            if time.time() - started > timeout:
                proc.kill()
                return {"ok": False, "error": "RVC conversion timed out", "log": "\n".join(lines)}
        proc.wait(timeout=60)
    except Exception as exc:  # noqa: BLE001
        try:
            proc.kill()
        except OSError:
            pass
        return {"ok": False, "error": f"RVC process failed: {exc}", "log": "\n".join(lines)}
    finally:
        try:
            cfg_path.unlink()
        except OSError:
            pass

    if proc.returncode != 0:
        tail = [ln.strip() for ln in lines if ln.strip()]
        detail = tail[-1].replace("[rvc]", "").strip() if tail else ""
        if len(detail) > 200:
            detail = detail[:197] + "..."
        message = f"RVC exited with code {proc.returncode}"
        if detail:
            message += f": {detail}"
        return {"ok": False, "error": message, "log": "\n".join(lines[-40:])}
    if not os.path.isfile(output_wav):
        return {"ok": False, "error": "RVC produced no output file", "log": "\n".join(lines[-40:])}

    return {"ok": True, "wav": output_wav, "log": "\n".join(lines[-40:]), "f0_method": f0}
