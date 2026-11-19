"""Render orchestration: score -> sung source -> RVC voice -> master."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from . import effects, rvc
from .phonemes import G2P
from .synth import Singer, note_phoneme_map

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RENDERS = DATA / "renders"
ASSETS = ROOT / "assets"
SR = 16000

_G2P: G2P | None = None


def g2p() -> G2P:
    global _G2P
    if _G2P is None:
        _G2P = G2P(str(ASSETS / "cmudict.dict"))
    return _G2P


class Cancelled(Exception):
    pass


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (text or "song").strip()).strip("-")
    return s[:40] or "song"


def _num(value, default, lo=None, hi=None):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    if lo is not None and v < lo:
        return lo
    if hi is not None and v > hi:
        return hi
    return v


def render(project: dict, options: dict | None = None, progress=None, log=None,
           cancel=None) -> dict:
    """Render a project. Returns render metadata (also written to disk)."""
    options = options or {}
    t_start = time.time()
    warnings: list[str] = []
    lines: list[str] = []

    def say(msg: str) -> None:
        lines.append(msg)
        if log:
            log(msg)

    def tick(value: float) -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if progress:
            progress(max(0.0, min(1.0, value)))

    bpm = _num(project.get("bpm", 120), 120, 20, 300)
    voice = dict(project.get("voice") or {})
    tracks = project.get("tracks") or []
    if not isinstance(tracks, list):
        tracks = []

    all_notes = []
    for track in tracks:
        if not isinstance(track, dict) or track.get("muted"):
            continue
        notes = track.get("notes") or []
        if isinstance(notes, list):
            all_notes.extend(n for n in notes if isinstance(n, dict))
    if not all_notes:
        raise ValueError("The project has no notes. Add notes to the piano roll first.")

    say(f"score: {len(all_notes)} notes, {bpm:.0f} BPM")
    singer = Singer(g2p(), SR)

    # ---- render each track's vocal line -----------------------------------
    mixed = None
    per_track = 0
    for track in tracks:
        if not isinstance(track, dict) or track.get("muted"):
            continue
        notes = [n for n in (track.get("notes") or []) if isinstance(n, dict)]
        if not notes:
            continue
        per_track += 1
        label = track.get("name") or f"Track {per_track}"
        say(f"singing track: {label}")
        gained = float(_num(track.get("gain", 1.0), 1.0, 0.0, 2.0))
        base = 0.05 + 0.5 * (per_track - 1) / max(1, len(tracks))

        def track_progress(p, base=base, count=len(tracks)):
            tick(base + p * (0.62 - base) / max(1, count))

        samples, _plans = singer.render(notes, bpm, voice, progress=track_progress)
        if mixed is None:
            mixed = [0.0] * len(samples)
        if len(samples) > len(mixed):
            mixed.extend([0.0] * (len(samples) - len(mixed)))
        for i, s in enumerate(samples):
            mixed[i] += s * gained

    if mixed is None:
        raise ValueError("Nothing to render.")

    # normalise the source so RVC gets a healthy level
    mixed = effects.normalize(mixed, 0.92)
    tick(0.68)
    RENDERS.mkdir(parents=True, exist_ok=True)
    job_id = options.get("jobId") or f"{_slug(project.get('name'))}-{int(time.time())}"
    source_path = RENDERS / f"{job_id}_source.wav"
    effects.write_wav(str(source_path), mixed, SR)
    say(f"source vocal written ({len(mixed) / SR:.1f}s)")

    # ---- RVC conversion ---------------------------------------------------
    mode = str(options.get("mode", "auto"))
    voice_id = options.get("voiceId") or voice.get("id")
    selected = rvc.get_voice(voice_id)
    converted_path = None
    rvc_info = {"used": False, "reason": None}
    final_samples = mixed
    final_sr = SR

    use_rvc = mode != "source"
    if use_rvc and selected is None:
        rvc_info["reason"] = "No voicebank selected — using the built-in DSP singer."
        warnings.append(rvc_info["reason"])
        say(rvc_info["reason"])
    elif use_rvc:
        status = rvc.check_rvc()
        if not status["available"]:
            rvc_info["reason"] = f"RVC unavailable ({status['reason']}). Using DSP singer."
            warnings.append(rvc_info["reason"])
            say(rvc_info["reason"])
        else:
            say(f"RVC voice: {selected['name']} ({status.get('device', 'cpu')})")
            tick(0.72)
            out_wav = RENDERS / f"{job_id}_voice.wav"
            pitch = int(_num(options.get("pitch", voice.get("pitch", 0)), 0, -24, 24))
            pitch += int(selected.get("pitch") or 0)
            idx_rate = _num(options.get("indexRate", voice.get("indexRate", 0.75)), 0.75, 0.0, 1.0)
            protect = _num(options.get("protect", voice.get("protect", 0.33)), 0.33, 0.0, 0.5)
            volume_env = _num(voice.get("volumeEnvelope", 0.9), 0.9, 0.0, 1.0)
            f0_method = str(options.get("f0Method", voice.get("f0Method", "rmvpe")))
            sid = int(_num(voice.get("sid", selected.get("sid", 0)), 0, 0, 999))
            result = rvc.convert(
                str(source_path),
                str(out_wav),
                selected,
                pitch=pitch,
                f0_method=f0_method,
                index_rate=idx_rate,
                protect=protect,
                volume_envelope=volume_env,
                sid=sid,
                log=say,
            )
            if result.get("ok"):
                try:
                    final_samples, final_sr, _ch = effects.read_wav(result["wav"])
                    converted_path = Path(result["wav"])
                    rvc_info = {
                        "used": True,
                        "reason": "converted",
                        "voice": selected["name"],
                        "f0Method": result.get("f0_method"),
                        "pitch": pitch,
                        "indexRate": idx_rate,
                        "protect": protect,
                    }
                    say(f"RVC converted at {final_sr} Hz")
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Could not read RVC output: {exc}")
            else:
                rvc_info["reason"] = result.get("error") or "RVC conversion failed"
                warnings.append(f"RVC failed, kept DSP singer: {rvc_info['reason']}")
                say(f"RVC failed: {rvc_info.get('log', '')[-600:]}")

    tick(0.9)

    # ---- master -----------------------------------------------------------
    do_comp = bool(voice.get("compressor", True))
    reverb_mix = _num(voice.get("reverb", 0.12), 0.12, 0.0, 1.0)
    gain = _num(voice.get("gain", 0.9), 0.9, 0.0, 1.5)
    final = effects.master(
        final_samples,
        final_sr,
        do_compress=do_comp,
        reverb_mix=reverb_mix,
        gain=gain,
    )
    final_path = RENDERS / f"{job_id}_final.wav"
    effects.write_wav(str(final_path), final, final_sr)
    tick(0.97)

    peaks = effects.waveform_peaks(final, 900)
    phones = note_phoneme_map(all_notes, bpm, g2p())
    meta = {
        "jobId": job_id,
        "project": project.get("name"),
        "audioUrl": f"/api/audio/{final_path.name}",
        "sourceUrl": f"/api/audio/{source_path.name}",
        "duration": round(len(final) / final_sr, 3),
        "sampleRate": final_sr,
        "peaks": peaks,
        "rvc": rvc_info,
        "warnings": warnings,
        "phones": phones,
        "log": lines[-60:],
        "elapsed": round(time.time() - t_start, 2),
        "created": int(time.time()),
    }
    tick(1.0)
    return meta
