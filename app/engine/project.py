"""Project model helpers (shared by the server and the engine)."""

from __future__ import annotations

import copy
import re
import time
import uuid

DEFAULT_VOICE = {
    "id": None,
    "pitch": 0,
    "indexRate": 0.75,
    "protect": 0.33,
    "f0Method": "rmvpe",
    "volumeEnvelope": 0.9,
    "sid": 0,
    "transpose": 0,
    "formantShift": 1.0,
    "vibratoRate": 5.6,
    "vibratoDepth": 0.20,
    "vibratoDelay": 0.16,
    "vibratoRamp": 0.28,
    "scoop": 0.12,
    "breathiness": 0.12,
    "brightness": 0.55,
    "jitter": 0.006,
    "dynamics": 0.5,
    "reverb": 0.12,
    "compressor": True,
    "gain": 0.9,
}


def new_id(prefix: str = "n") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def note(midi: int, start: float, dur: float, lyric: str, velocity: float = 0.82) -> dict:
    return {
        "id": new_id(),
        "midi": int(midi),
        "start": round(float(start), 4),
        "dur": round(float(dur), 4),
        "lyric": lyric,
        "velocity": velocity,
    }


def _demo_notes() -> list[dict]:
    raw = [
        # bar 1
        (67, 0.0, 0.5, "hel"), (67, 0.5, 0.5, "lo"),
        (69, 1.0, 1.0, "world"), (72, 2.0, 0.5, "we"),
        (71, 2.5, 0.5, "are"), (69, 3.0, 1.0, "sing"),
        # bar 2
        (67, 4.0, 0.5, "ing"), (64, 4.5, 0.5, "in"),
        (65, 5.0, 1.0, "the"), (67, 6.0, 0.5, "light"),
        (69, 6.5, 0.5, "of"), (67, 7.0, 1.0, "dawn"),
        # bar 3
        (72, 8.0, 1.0, "hear"), (71, 9.0, 0.5, "my"),
        (69, 9.5, 0.5, "voice"), (67, 10.0, 1.0, "rise"),
        (69, 11.0, 1.0, "up"),
        # bar 4
        (72, 12.0, 0.5, "in"), (71, 12.5, 0.5, "to"),
        (69, 13.0, 1.0, "the"), (67, 14.0, 2.0, "sky"),
    ]
    return [note(m, s, d, l, 0.86) for m, s, d, l in raw]


def _harmony_notes() -> list[dict]:
    raw = [
        (64, 0.0, 1.0, "ooh"), (64, 1.0, 1.0, "ooh"), (67, 2.0, 1.0, "ooh"),
        (64, 3.0, 1.0, "ooh"),
        (64, 4.0, 1.0, "ah"), (60, 5.0, 1.0, "ah"), (62, 6.0, 1.0, "ah"),
        (64, 7.0, 1.0, "ah"),
        (67, 8.0, 2.0, "ooh"), (64, 10.0, 2.0, "ooh"),
        (67, 12.0, 2.0, "ooh"), (64, 14.0, 2.0, "ooh"),
    ]
    return [note(m, s, d, l, 0.42) for m, s, d, l in raw]


DEMO_COLORS = ["#d81f2a", "#ff8a1e", "#e0b23c", "#7cbf62", "#4f9fb8", "#c05a8e"]


def default_project(name: str = "Second Child", bpm: float = 104) -> dict:
    return {
        "schema": 2,
        "id": new_id("prj"),
        "name": name,
        "bpm": bpm,
        "timeSignature": [4, 4],
        "key": "C major",
        "tracks": [
            {
                "id": new_id("trk"),
                "name": "Lead",
                "voiceId": None,
                "gain": 1.0,
                "pan": 0.0,
                "muted": False,
                "color": DEMO_COLORS[0],
                "notes": _demo_notes(),
            },
            {
                "id": new_id("trk"),
                "name": "Harmony",
                "voiceId": None,
                "gain": 0.38,
                "pan": 0.15,
                "muted": False,
                "color": DEMO_COLORS[1],
                "notes": _harmony_notes(),
            },
        ],
        "voice": copy.deepcopy(DEFAULT_VOICE),
        "loop": {"start": 0, "end": 16},
        "created": int(time.time()),
        "updated": int(time.time()),
    }


def normalise(project: dict) -> dict:
    """Make an incoming project safe to render."""
    if not isinstance(project, dict):
        raise ValueError("project must be an object")
    out = copy.deepcopy(project)
    out["schema"] = 2
    out.setdefault("id", new_id("prj"))
    name = str(out.get("name") or "Untitled").strip()[:80]
    out["name"] = name or "Untitled"
    try:
        bpm = float(out.get("bpm", 120))
    except (TypeError, ValueError):
        bpm = 120.0
    out["bpm"] = max(20.0, min(300.0, bpm))
    ts = out.get("timeSignature") or [4, 4]
    try:
        out["timeSignature"] = [int(ts[0]), int(ts[1])]
    except (TypeError, ValueError, IndexError):
        out["timeSignature"] = [4, 4]

    voice = copy.deepcopy(DEFAULT_VOICE)
    voice.update(out.get("voice") or {})
    out["voice"] = voice

    tracks = out.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        tracks = [{
            "id": new_id("trk"),
            "name": "Lead",
            "gain": 1.0,
            "pan": 0.0,
            "muted": False,
            "color": DEMO_COLORS[0],
            "notes": [],
        }]
    clean_tracks = []
    for i, track in enumerate(tracks[:24]):
        if not isinstance(track, dict):
            continue
        notes = []
        for n in (track.get("notes") or [])[:4000]:
            if not isinstance(n, dict):
                continue
            try:
                midi = int(round(float(n.get("midi", 60))))
                start = max(0.0, float(n.get("start", 0)))
                dur = max(0.02, float(n.get("dur", 1)))
                vel = max(0.05, min(1.0, float(n.get("velocity", 0.82))))
            except (TypeError, ValueError):
                continue
            notes.append({
                "id": str(n.get("id") or new_id()),
                "midi": max(12, min(120, midi)),
                "start": round(start, 4),
                "dur": round(min(64.0, dur), 4),
                "lyric": str(n.get("lyric", "la"))[:60],
                "velocity": round(vel, 3),
            })
        clean_tracks.append({
            "id": str(track.get("id") or new_id("trk")),
            "name": str(track.get("name") or f"Track {i + 1}")[:40],
            "voiceId": track.get("voiceId"),
            "gain": max(0.0, min(2.0, float(track.get("gain", 1.0) or 0))),
            "pan": max(-1.0, min(1.0, float(track.get("pan", 0.0) or 0))),
            "muted": bool(track.get("muted")),
            "color": str(track.get("color") or DEMO_COLORS[i % len(DEMO_COLORS)]),
            "notes": notes,
        })
    out["tracks"] = clean_tracks
    out["updated"] = int(time.time())
    return out


def slugify(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._ -]+", "", name or "").strip().replace(" ", "-")
    return s[:60] if s else "untitled"
