# agent.md — read this before touching anything

This file is the briefing for AI coding agents working in this repository.
It explains what the project is, how the pieces fit, how to run it, and the rules
that keep it working.

---

## 1. What this project is

**AsukaRVC-SVC** (short: **ARVC-SVC**) is a local-first, Vocaloid-style **singing voice
synthesizer** with a desktop-app feel, delivered as a web app. You draw a melody + lyrics on
a piano roll, press **Render voice**, and get a sung WAV.

The **voice provider is RVC** (Retrieval-based Voice Conversion). RVC is the point
of the project — everything else exists to feed it a clean, expressive carrier
vocal and to master the result.

```
piano roll ──> G2P ──> formant singer ──> RVC ──> master bus ──> WAV
 (score)     (phonemes) (16 kHz carrier) (timbre)  (comp/verb/limiter)
```

Because the carrier already contains the exact melody, timing, vibrato and
consonants, RVC's F0 guidance keeps the *performance* and only replaces the
*timbre* with a trained voicebank.

**It must always work without RVC.** No venv, no `.pth`, no GPU → the app still
renders with the built-in DSP singer and says so in the UI. Never make the app
hard-depend on the RVC environment.

---

## 2. Hard rules

1. **The GUI is plain HTML + CSS + JavaScript.** No React, no Vue, no bundler, no
   npm, no CDN, no build step. `app/web/index.html`, `app/web/styles.css`,
   `app/web/app.js` are loaded directly by the browser.
2. **The fullstack app is hosted by Gradio.** Gradio (running on its bundled
   uvicorn/FastAPI stack) serves the JSON API + the static studio, and mounts a
   small "Voice Lab" Blocks app at `/manage`. Entry point: `app/gradio_app.py`.
   `app/server.py` is the dependency-free stdlib fallback and the module that
   owns shared state (jobs, projects, voices, render).
3. **Do not rewrite `programs/rvc/`.** That is vendored RVC inference code
   (`infer/`, `configs/`, `lib/`). Treat it as read-only. Adapt the app around
   it, not the other way round.
4. **The backend engine is stdlib-only and runs on the system Python (3.15).**
   Torch/faiss/librosa live in the isolated `.venv-rvc` (Python 3.12) and are
   reached only through a subprocess (`app/engine/rvc_worker.py`). Do not import
   torch into `app/server.py`, `app/engine/render.py`, etc.
5. **Local only.** Server binds `127.0.0.1`. No accounts, no telemetry, no cloud.
6. **Files are UTF-8.** Use `encoding="utf-8"` on every text read/write. Do not
   let PowerShell/Python default to cp1252 — it corrupts arrows and lyrics.
7. **Style:** 4-space indent, `from __future__ import annotations`, `pathlib`
   over `os.path`, type hints on public functions, small pure helpers, comments
   only where intent is non-obvious. Match the surrounding code.
8. **Theming is token-driven.** Every colour lives in a `:root[data-theme="…"]`
   block in `app/web/styles.css`; no hardcoded UI colours in HTML/JS. Canvas code
   uses the `TP` palette (see `refreshPalette()` in `app.js`). The default theme
   is **`asuka`** (Unit-02 red / signal orange / warm charcoal) and the look is
   deliberately flat and hardware-panel-like — not glassy, blurred or glowing.
   Presets live in `THEMES`; persisted at `localStorage['arvc-svc.theme.v1']`.

---

## 3. Architecture

### Request path

| Layer | File | Responsibility |
| --- | --- | --- |
| Studio UI | `app/web/index.html` + `styles.css` + `app.js` | piano roll, tracks, inspector, waveform, jobs, modals, undo, shortcuts |
| Host / API | `app/gradio_app.py` | FastAPI routes, static mount, Gradio "Voice Lab" at `/manage`, uvicorn launcher |
| Shared state | `app/server.py` | job registry + threads, project save/load/list, voice REST, audio Range streaming, RVC status |
| Engine | `app/engine/*` | G2P, singer, effects, render pipeline, RVC bridge |
| RVC | `programs/rvc/` (vendored) | actual voice conversion model code |

`app/gradio_app.py` imports `app.server` as `base` and re-uses its state
(`JOBS`, `start_render`, `list_projects`, `save_project`, `warm_rvc`,
`RVC_STATUS`, `VERSION`, `SAFE_FILE`, `SAFE_ID`, `_g2p`). Keep those names stable
or update both servers.

### Render pipeline (`app/engine/render.py`)

1. `project.normalise()` — clamp/validate the incoming project.
2. For each unmuted track: `Singer.render(notes, bpm, voice, progress)` at
   **16 000 Hz** (`SR`), summing tracks with their `gain`.
3. `effects.normalize(mixed, 0.92)` → `data/renders/<job>_source.wav`.
4. If a voicebank is selected **and** RVC is available → `rvc.convert(...)`
   writes `<job>_voice.wav`. Pitch = job pitch + voicebank pitch. Any failure
   keeps the DSP carrier (never lose the take).
5. `effects.master(...)` (compressor → reverb → gain → soft limiter) →
   `<job>_final.wav`, plus waveform peaks + per-note phoneme map in the metadata.
6. Progress is reported 0.0–1.0 through a callback; cancellation via a
   `threading.Event` raises `render.Cancelled`.

### G2P and singing (`app/engine/phonemes.py`, `synth.py`)

- `G2P` loads `assets/cmudict.dict` when present (downloaded CMUdict) and falls
  back to a rule-based letter-to-sound converter plus a small `SING_LEXICON`
  for sung syllables (`la`, `na`, `ooh`, `yeah`, …).
- `note_phoneme_map(notes, bpm, g2p)` gives each note its phoneme segment
  timings — this powers the phoneme inspector and the render metadata.
- `Singer` is a formant/glottal-pulse synthesizer with portamento, delayed
  vibrato, scoops, breathiness, brightness, formant shift, jitter and dynamics.
  Deterministic enough for tests: same project → same duration.

### RVC bridge (`app/engine/rvc.py`, `rvc_worker.py`)

- `rvc_python()` finds `.venv-rvc\Scripts\python.exe` (or `$RVC_PYTHON`).
- `check_rvc(force)` probes torch/librosa/faiss/soundfile, records torch version,
  device, and whether RMVPE / ContentVec assets exist; cached 1 h in
  `data/rvc_status.json`.
- `list_voices()` / `install_voice()` / `delete_voice()` manage `models/**`
  `.pth` (+ sibling `.index`, auto-detected) with metadata in `data/voices.json`.
  Voice ids are a sha1 of the model's path relative to `models/`.
- `convert()` spawns `rvc_worker.py` inside `.venv-rvc` with cwd = repo root and
  `PYTHONPATH` including the root. `VoiceConverter.convert_audio` swallows its
  own exceptions, so **always verify the output file exists and is non-empty**.

---

## 4. Repository map

```
agent.md                  this file
start.ps1 / start.bat     launch (Gradio host if installed, else stdlib server)
setup_rvc.bat             one-time RVC environment installer
requirements-rvc.txt      deps for .venv-rvc
app/
  gradio_app.py           Gradio-hosted fullstack (primary entry point)
  server.py               stdlib HTTP server + shared job/project/render state
  engine/
    phonemes.py           phoneme table, CMUdict + rule G2P, singing lexicon
    synth.py              formant singer, vibrato/breath, note→phoneme timing
    effects.py            WAV I/O, resample, compressor, reverb, limiter, peaks
    render.py             score → source → RVC → master pipeline
    rvc.py                env probe, voicebank library, subprocess bridge
    rvc_worker.py         executed inside .venv-rvc
    project.py            project schema, demo song ("Second Child"), normalisation
  web/
    index.html            studio shell (loaded as-is)
    styles.css            theme token blocks + flat/retro studio styling
    app.js                piano roll, state, render polling, upload, undo, theme picker
assets/cmudict.dict       optional CMUdict (downloaded)
models/<voice>/…pth       your voicebanks (+ optional .index)
data/projects/*.json      saved projects
data/renders/*.wav        render output (_source, _voice, _final)
data/voices.json          voice metadata
data/rvc_status.json      cached probe result
programs/rvc/             vendored RVC inference (do not modify)
tools/setup_rvc.ps1       uv-based installer (Python 3.12 + torch + assets)
tools/download_assets.py  ContentVec / RMVPE / FCPE / CMUdict downloader
```

---

## 5. Running it

```powershell
# first time, optional but needed for real RVC voices
.\setup_rvc.bat

# daily driver
.\start.bat            # or: .\start.ps1
# → http://127.0.0.1:8777/        studio (HTML/CSS/JS)
# → http://127.0.0.1:8777/manage  Gradio "Voice Lab"
```

Explicit forms:

```powershell
# full stack on Gradio (uvicorn/FastAPI): studio + API + /manage
.venv-rvc\Scripts\python.exe app\gradio_app.py --port 8777 --no-browser
.venv-rvc\Scripts\python.exe -m uvicorn app.gradio_app:app --host 127.0.0.1 --port 8777

# dependency-free fallback (system Python, standard library only)
python app\server.py --port 8777 --no-browser
```

`start.ps1` prefers `.venv-rvc` and picks `app/gradio_app.py` when `gradio` is
importable, otherwise `app/server.py`. Keep that behaviour.

There is no formal test suite. Verify end to end with the smoke script (stdlib only,
server must already be running) and ad-hoc API calls:

```powershell
C:\Users\Admin\AppData\Local\Python\pythoncore-3.15-64\python.exe tools\smoke_gradio.py
Invoke-RestMethod http://127.0.0.1:8777/api/state | ConvertTo-Json -Depth 4
Invoke-RestMethod "http://127.0.0.1:8777/api/g2p?text=hello%20world"
# POST /api/render {"project": <project>, "options": {"mode":"auto"}}
```

`tools/smoke_gradio.py` renders the demo project, checks job progress, fetches the WAV,
tests a Range request, then touches `/manage`. It exits non-zero on failure.

---

## 6. HTTP API (both servers implement it)

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | studio (index.html) |
| GET | `/static/*` | JS/CSS assets |
| GET | `/api/health` | liveness + version |
| GET | `/api/state` | version, RVC status, voices, projects, demo project, lexicon size |
| GET | `/api/demo` | demo project only |
| GET / POST | `/api/projects` | list / save (`?id=` to load one) |
| DELETE | `/api/projects?id=` | delete a project |
| POST | `/api/render` | `{project, options}` → job (starts a thread immediately) |
| GET | `/api/jobs` | last 20 jobs |
| GET | `/api/job?id=` | progress, log, result |
| POST | `/api/cancel` | `{id}` → set cancel flag |
| GET / POST / DELETE | `/api/voices` | list / multipart upload `.pth` + `.index` / delete |
| POST | `/api/rvc/check` | re-probe the RVC env in a thread |
| GET | `/api/rvc` | cached probe status |
| GET | `/api/g2p?text=&midi=&dur=&bpm=` | phonemes per word + per note |
| GET | `/api/audio/{name}` | stream WAV (Range supported) |
| GET | `/api/download/{name}` | WAV as attachment |

Jobs are in-memory: `{id, status, progress, message, log[], result, error}` with
status `queued | running | done | error | cancelled`. Poll `/api/job?id=`.

---

## 7. Project JSON schema (schema 2)

```jsonc
{
  "schema": 2,
  "id": "prj_…", "name": "Second Child", "bpm": 104,
  "timeSignature": [4, 4], "key": "C major",
  "tracks": [{
    "id": "trk_…", "name": "Lead", "gain": 1.0, "pan": 0.0,
    "muted": false, "color": "#d81f2a", "voiceId": null,
    "notes": [{ "id": "n_…", "midi": 60, "start": 0.0, "dur": 1.0,
                "lyric": "la", "velocity": 0.82 }]
  }],
  "voice": {
    "id": null, "pitch": 0, "indexRate": 0.75, "protect": 0.33,
    "volumeEnvelope": 0.9, "sid": 0, "transpose": 0, "formantShift": 1.0,
    "vibratoRate": 5.6, "vibratoDepth": 0.2, "vibratoDelay": 0.16,
    "vibratoRamp": 0.28, "scoop": 0.12, "breathiness": 0.12,
    "brightness": 0.55, "jitter": 0.006, "dynamics": 0.5,
    "reverb": 0.12, "compressor": true, "gain": 0.9
  },
  "loop": { "start": 0, "end": 16 }
}
```

`start`/`dur` are in **beats**; `midi` is the pitch. `voice` is a single global
vocal chain — **voice conversion happens once per render on the mixed carrier**,
not per track (CPU cost). Any unknown/invalid field must survive
`project.normalise()` with a sane default.

---

## 8. RVC voicebanks

```
models/
  my-voice/
    my-voice.pth            required (RVC v1 or v2: Applio, RVC WebUI, …)
    added_IVF….index        optional FAISS index — better timbre
```

Install via the studio's Upload button or `/manage`. Do not hand-edit
`data/voices.json` while the server is running. A male model singing high parts
needs *Pitch shift*; *Formant* affects the carrier instead.

Assets required for conversion live under `programs/rvc/models/`:
`predictors/rmvpe.pt`, `predictors/fcpe.pt`,
`embedders/contentvec/pytorch_model.bin` + `config.json`. Download with:

```powershell
.venv-rvc\Scripts\python.exe tools\download_assets.py
```

---

## 9. Gotchas / known traps

- **Encoding.** PowerShell 5.1 + `>` writes UTF-16; Python on Windows may default
  to cp1252. Always pass UTF-8 explicitly. README/agent docs contain `→`.
- **G2P is loaded once at server start.** Editing `phonemes.py` requires a server
  restart before `/api/g2p` reflects it.
- **Threads.** Job dicts are mutated from render threads. Take `JOBS_LOCK`
  (`RLock`) around reads/writes; never hold it during a render.
- **Job ids double as filenames** (`<slug>-<hex8>`). Keep them filename-safe;
  validate every user-supplied file/id with `SAFE_FILE` / `SAFE_ID`.
- **`VoiceConverter.convert_audio` fails silently.** Check the output WAV exists
  and headers are sane; surface worker stderr in the job log.
- **Torch >= 2.6 `weights_only`.** `torch.load` now defaults to `weights_only=True`,
  which rejects the pickled metadata inside many RVC `.pth` files. `rvc_worker.py`
  restores `weights_only=False` for locally installed models — keep that patch when
  touching the worker, and never load models from untrusted sources.
- **Worker cwd** must be the repo root with `PYTHONPATH` containing it, or
  `programs.rvc` imports break inside `.venv-rvc`.
- **Sample rate.** The carrier is 16 kHz by design (RVC expects it). Do not
  "upgrade" `SR` in `render.py` without also changing the RVC input contract.
- **Frontend has no framework.** `app.js` holds one mutable `state` object,
  explicit render functions, and an undo stack. Use event delegation, batch DOM
  writes, and avoid re-rendering the whole roll on pointer move.
- **Theme changes must reach the canvas.** CSS variables do not trigger a repaint
  of `<canvas>`. After changing `data-theme` or the `--custom-*` vars, call
  `refreshPalette()` and redraw (handled by `applyTheme()`); read canvas colours
  from `TP`/`cssVar()`, never from literal hex.
- **Custom theme uses `color-mix()`.** `--custom-bg`, `--custom-accent`,
  `--custom-accent-2` are set inline on `<html>` and the palette is derived in CSS.
  `hexA()` resolves any CSS colour through a hidden probe, so it copes with
  `color-mix()` results; do not revert it to naive hex parsing.
- **No CDN.** All CSS/JS/fonts must be local; the app has to work offline.
- **Don't leave test artifacts** in `models/`, `data/renders/` or
  `data/projects/`. Delete dummy voicebanks and throwaway renders.
- Gradio's file inputs return **paths**, not bytes — read the path before
  calling `install_voice`.
- Gradio mounting: `gr.mount_gradio_app(app, blocks, path="/manage")` must be the
  last step (it returns the same FastAPI app). Static files are mounted before
  the Gradio mount so `/static` is never shadowed, and `NoCacheStatic` adds
  `Cache-Control: no-cache` so editing `app.js`/`styles.css` shows up on reload.

---

## 10. Definition of done for a change

- `python app/gradio_app.py --no-browser` starts, `/` loads the studio with **no
  console errors**, `/manage` renders the Voice Lab.
- A render from the demo project produces `<job>_final.wav`, the waveform draws,
  and the RVC badge text is truthful (ready / unavailable + reason).
- Rendering still works with `.venv-rvc` deleted or renamed (DSP fallback).
- Theme selector shows the four presets + Custom; switching recolours chrome and
  both canvases live, and the choice survives a reload. Default on a fresh browser
  is **Asuka Soryu**.
- No new dependencies in `requirements.txt` (stdlib only). Anything RVC-related
  goes in `requirements-rvc.txt` and is installed by `tools/setup_rvc.ps1`.
- Docs updated: `README.md` for humans, this file for agents.
