# AsukaRVC-SVC (ARVC-SVC) — RVC Singing Studio

A Vocaloid-style singing voice synthesizer whose **voice engine is RVC** (Retrieval-based
Voice Conversion). Write a melody and lyrics on a piano roll, press **Render voice**, and
AsukaRVC-SVC:

1. turns lyrics into phonemes (CMU dictionary + rule-based fallback),
2. sings them with a built-in formant/glottal synthesizer at **exactly the pitch curve,
   timing, vibrato and consonants** of your score (16 kHz),
3. converts that performance with your **RVC voicebank** (`.pth` + optional `.index`),
4. masters the result (compressor, reverb, limiter) and gives you a WAV.

Because the carrier vocal already contains the melody, RVC's F0 guidance preserves your
performance while replacing the timbre with the trained voice.

```
piano roll ──► phonemes ──► formant singer (16 kHz) ──► RVC ──► master ──► WAV
   (score)      (G2P)          (carrier performance)    (timbre)
```

---

## Quick start

```bat
start.bat
```

The UI opens at <http://127.0.0.1:8777>. It runs **immediately** with the built-in DSP
singer — no Python packages required beyond the standard library. The demo song is loaded
on first launch.

`start.bat` prefers the **Gradio-hosted fullstack** app (`app/gradio_app.py`): Gradio's
uvicorn/FastAPI server serves the plain HTML/CSS/JS studio and the JSON API, and owns the
**Voice Lab** page at <http://127.0.0.1:8777/manage>. If Gradio is not installed it falls
back to the dependency-free stdlib server (`app/server.py`). Both expose the same API.

### Enable RVC voices (one time)

```bat
setup_rvc.bat
```

This uses [uv](https://docs.astral.sh/uv/) to install Python 3.12 into `.python\`, creates
`.venv-rvc` with PyTorch and the RVC inference stack, and downloads ContentVec, RMVPE, FCPE
and the CMU dictionary (~600 MB).

Then either drop a RVC `.pth` (+ optional `.index`) into `models\`, or use **Upload** in the
Voicebanks panel. Select it in the inspector and hit **Render voice**.

> CPU-only machines work. A 10-second phrase typically converts in a few seconds on GPU and
> 20–60 s on CPU with RMVPE. The app falls back to the DSP singer if RVC fails or no
> voicebank is selected.

---

## Features

- **Piano roll** — draw, drag, resize, duplicate, marquee-select, per-note lyrics and velocity.
- **Lyrics → phonemes** — full CMUdict (once downloaded) plus a letter-to-sound fallback;
  per-note phoneme inspector shows timing.
- **Expressive singer** — portamento, delayed vibrato, scoops, breathiness, brightness,
  formant shift, jitter, dynamics.
- **RVC controls** — voicebank, pitch shift, speaker ID, F0 method (RMVPE / CREPE / FCPE /
  hybrid), index rate, protect, volume envelope.
- **Mix bus** — per-track gain/mute, compressor, reverb, master gain, soft limiter.
- **Projects** — saved as JSON in `data/projects/`, plus demo and empty-project templates.
- **A/B** — compare the converted voice with the raw DSP carrier.
- **Plain web GUI** — the studio is hand-written HTML/CSS/JS: no npm, no build step, no
  CDN. Gradio hosts the fullstack app and serves the Voice Lab; the stdlib server is a
  dependency-free fallback.
- **Themes** — four presets plus a custom three-colour theme; see [Themes](#themes).

### Themes

The default look is **Asuka Langley Soryu** (Unit-02 red `#d81f2a`, signal orange `#ff8a1e`,
warm charcoal), deliberately flat and hardware-panel-like rather than glassy or glossy.
Pick a theme from the **Theme** selector in the top bar, or choose **Custom** to open the
colour dialog.

| Preset | Description |
| --- | --- |
| `Asuka Soryu` | Unit-02 red / orange / charcoal — **default** |
| `Unit-01` | Violet shell, acid-green highlight |
| `NERV terminal` | Warm paper, black ink, signal red (light) |
| `Midnight` | Neutral blue-grey for long sessions |
| `Custom` | Background, accent and highlight colours of your choice |

The theme sets `<html data-theme="…">`; the Custom theme also writes three `--custom-*`
custom properties and derives the remaining palette with CSS `color-mix()`. Canvas drawing
(piano roll and waveform) reads the same tokens, so it recolours live. The choice is stored
in `localStorage` under `arvc-svc.theme.v1` and does not touch project files.

### Keyboard

| Key | Action |
| --- | --- |
| `Space` | Play / pause (renders first if needed) |
| `Ctrl+Enter` | Render |
| `V` / `N` / `E` | Select / draw / erase tool |
| `Del` | Delete selected notes |
| `Ctrl+Z`, `Ctrl+Shift+Z` | Undo / redo |
| `Ctrl+S` | Save project |
| `Ctrl+D` | Duplicate selection |
| `Tab` | Jump to the next note's lyric while editing |
| Arrows | Move notes (snap) / transpose |

---

## Adding voicebanks

RVC v1 and v2 models work (Applio, RVC WebUI, any compatible trainer).

```
models/
  my-voice/
    my-voice.pth          ← required
    added_IVF...index     ← optional FAISS index, improves timbre
```

The app auto-detects a sibling `.index`. Voice metadata (display name, pitch offset,
speaker id) lives in `data/voices.json` and is managed by the UI.

**Pitch:** If a male model sings too low for your melody, raise *Pitch shift* or use
*Formant* (affects the carrier). The score is always preserved.

---

## Project layout

```
agent.md               briefing for AI agents working on the repo
app/
  gradio_app.py        Gradio + FastAPI host: studio, JSON API, Voice Lab at /manage
  server.py            stdlib HTTP server + JSON API + audio streaming (fallback,
                       also owns the shared job / project / render state)
  engine/
    phonemes.py        phoneme acoustic table + CMUdict/rule G2P
    synth.py           formant singer (glottal pulse, formants, vibrato)
    effects.py         WAV IO, compressor, reverb, limiter, resample
    render.py          score → source → RVC → master pipeline
    rvc.py             RVC environment probe, voicebank library, subprocess bridge
    rvc_worker.py      runs inside .venv-rvc
    project.py         project schema, demo song, validation
  web/                 index.html + app.js + styles.css
assets/                cmudict.dict (optional)
models/                your RVC voicebanks
data/                  projects, renders, caches
programs/rvc/          RVC inference code (already present)
tools/
  setup_rvc.ps1        one-time environment installer
  download_assets.py   pretrained model downloader
  smoke_gradio.py      end-to-end API smoke test (server must be running)
```

`agent.md` explains the architecture and conventions for AI agents working on the repo.

### HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/state` | voices, projects, RVC status, demo project |
| GET | `/api/projects` | list / load (`?id=`) |
| POST | `/api/projects` | save project |
| POST | `/api/render` | start render job |
| GET | `/api/job?id=` | job progress / result |
| GET | `/api/voices` | voicebank list |
| POST | `/api/voices` | upload `.pth` (+ `.index`) |
| GET | `/api/g2p?text=` | phoneme breakdown |
| GET | `/api/audio/<file>` | stream WAV (Range supported) |
| GET | `/api/download/<file>` | download WAV |
| GET | `/manage` | Gradio "Voice Lab" (Gradio host only) |

---

## Notes & troubleshooting

- **RVC chip says “not installed”** — run `setup_rvc.bat`, then **Re-check**.
- **RVC conversion fails** — the job log in the bottom panel shows the worker output. The
  DSP render is kept as a fallback, so you never lose the take. Most failures are missing
  voicebank files, a corrupt `.pth`, or a missing predictor (re-run
  `tools/download_assets.py` with the venv Python).
- **GPU** — the installer uses PyPI torch (CPU on Windows). For CUDA:
  `.venv-rvc\Scripts\python.exe -m pip install --force-reinstall torch torchaudio --index-url https://download.pytorch.org/whl/cu124`.
  CUDA also makes RMVPE much faster.
- **RAM** — RVC loads ContentVec + generator + F0 model; ~2–3 GB is typical.
- **Model licensing** — voicebanks carry their own licenses/consent requirements. Do not
  redistribute models you do not own.
- The server binds to `127.0.0.1` only; pass `--host 0.0.0.0` if you know what you are doing.
- `--port`, `--host`, `--no-browser` are supported by both `app/gradio_app.py` and
  `app/server.py`. Manual launch:
  `.venv-rvc\Scripts\python.exe app\gradio_app.py --port 8777 --no-browser`, or
  `uvicorn app.gradio_app:app --host 127.0.0.1 --port 8777`.
- **Voice Lab** (Gradio Blocks, mounted at `/manage`) lists installed voicebanks, re-probes
  the RVC engine, installs `.pth` / `.index` files and deletes voices. The studio itself is
  still plain HTML/CSS/JS — Gradio only hosts and serves it.

---

Built as a local-first desktop-style studio: no account, no cloud, your voice models stay
on disk.
