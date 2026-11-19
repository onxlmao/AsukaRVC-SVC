/* AsukaRVC-SVC / ARVC-SVC — RVC singing studio (frontend) */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const TRACK_COLORS = ['#d81f2a', '#ff8a1e', '#e0b23c', '#7cbf62', '#4f9fb8', '#c05a8e', '#c8bfae', '#e2563f'];

const midiToName = (m) => `${NOTE_NAMES[((m % 12) + 12) % 12]}${Math.floor(m / 12) - 1}`;
const midiToHz = (m) => 440 * Math.pow(2, (m - 69) / 12);
const uid = (p = 'n') => `${p}_${Math.random().toString(36).slice(2, 10)}`;
const fmtTime = (t) => {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
};

/* ------------------------------------------------------------------ state */
const S = {
  project: null,
  projectId: null,
  selection: new Set(),
  activeTrack: 0,
  tool: 'select',
  zoom: 1,
  vzoom: 1,
  topMidi: 80,
  scrollBeat: 0,
  snap: 0.25,
  defaultLyric: 'la',
  voices: [],
  projects: [],
  rvc: {},
  engine: {},
  playing: false,
  render: null,
  audio: new Audio(),
  audioMode: 'final',
  playAfter: false,
  jobId: null,
  jobTimer: null,
  undo: [],
  redo: [],
  dirty: false,
  drag: null,
  marquee: null,
  playheadBeat: 0,
  editingNote: null,
  phoneToken: 0,
  lastLyric: 'la',
};

const GUTTER = 56;
const RULER = 18;
const BASE_PPB = 112;

const canvas = $('#roll');
const ctx = canvas.getContext('2d');
const waveCanvas = $('#wave');
const wctx = waveCanvas.getContext('2d');

const ppb = () => BASE_PPB * S.zoom;
const noteH = () => 16 * S.vzoom;
const wrap = $('#rollWrap');

/* ------------------------------------------------------------------ theme */
const THEME_KEY = 'arvc-svc.theme.v1';
const THEMES = [
  { id: 'asuka', name: 'Asuka Soryu', note: 'Unit-02 red — default', swatches: ['#d81f2a', '#ff8a1e', '#120b0b'] },
  { id: 'unit01', name: 'Unit-01', note: 'Violet and acid green', swatches: ['#8d4fd8', '#a6e22e', '#0d0a14'] },
  { id: 'nerv', name: 'NERV terminal', note: 'Paper, ink, signal red', swatches: ['#c1121f', '#12614f', '#e9e2d2'] },
  { id: 'midnight', name: 'Midnight', note: 'Neutral blue-grey', swatches: ['#3f9fd8', '#e0b64a', '#0b0f15'] },
  { id: 'custom', name: 'Custom', note: 'Pick your own colours', swatches: ['#d81f2a', '#ff8a1e', '#120b0b'] },
];
const CUSTOM_DEFAULTS = { bg: '#120b0b', accent: '#d81f2a', accent2: '#ff8a1e' };
const themeState = { id: 'asuka', custom: { ...CUSTOM_DEFAULTS } };
let TP = {};

function readTheme() {
  try {
    const saved = JSON.parse(localStorage.getItem(THEME_KEY) || '{}');
    if (saved && THEMES.some((t) => t.id === saved.id)) themeState.id = saved.id;
    if (saved && saved.custom) themeState.custom = { ...CUSTOM_DEFAULTS, ...saved.custom };
  } catch (err) { /* first run / private mode */ }
}

function saveTheme() {
  try {
    localStorage.setItem(THEME_KEY, JSON.stringify({ id: themeState.id, custom: themeState.custom }));
  } catch (err) { /* ignore */ }
}

function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function refreshPalette() {
  TP = {
    rollBg: resolveColor(cssVar('--roll-bg'), '#150e0e'),
    rollBg2: resolveColor(cssVar('--roll-bg-2'), '#0f0909'),
    rowWhite: resolveColor(cssVar('--roll-row-white'), '#1b1212'),
    rowBlack: resolveColor(cssVar('--roll-row-black'), '#150e0e'),
    rowKey: resolveColor(cssVar('--roll-row-key'), 'rgba(255,138,30,.05)'),
    line: resolveColor(cssVar('--roll-line'), '#241716'),
    lineSoft: resolveColor(cssVar('--roll-line-soft'), '#1d1211'),
    bar: resolveColor(cssVar('--roll-bar'), 'rgba(216,31,42,.38)'),
    grid: resolveColor(cssVar('--roll-grid'), 'rgba(244,232,222,.06)'),
    ruler: resolveColor(cssVar('--roll-ruler'), '#0e0808'),
    rulerLine: resolveColor(cssVar('--roll-ruler-line'), '#3a1f1c'),
    text: resolveColor(cssVar('--roll-text'), '#a38479'),
    keyWhite: resolveColor(cssVar('--roll-key-white'), '#e7d8cb'),
    keyBlack: resolveColor(cssVar('--roll-key-black'), '#1a1010'),
    keyLabel: resolveColor(cssVar('--roll-key-label'), '#6a4e46'),
    noteInk: resolveColor(cssVar('--roll-note-ink'), '#180c0b'),
    accent: resolveColor(cssVar('--accent'), '#d81f2a'),
    accent2: resolveColor(cssVar('--accent-2'), '#ff8a1e'),
    playhead: resolveColor(cssVar('--playhead'), '#ff8a1e'),
    waveBg: resolveColor(cssVar('--wave-bg'), '#0f0909'),
    waveLine: resolveColor(cssVar('--wave-line'), '#2c1a18'),
    waveText: resolveColor(cssVar('--wave-text'), '#6c4f47'),
  };
}

function syncThemeSelect() {
  const sel = $('#themeSel');
  if (!sel) return;
  if (!sel.options.length) {
    for (const theme of THEMES) {
      const opt = document.createElement('option');
      opt.value = theme.id;
      opt.textContent = theme.name;
      sel.appendChild(opt);
    }
  }
  sel.value = themeState.id;
}

function applyTheme(id, custom) {
  if (custom) themeState.custom = { ...themeState.custom, ...custom };
  themeState.id = THEMES.some((t) => t.id === id) ? id : 'asuka';
  const root = document.documentElement;
  root.dataset.theme = themeState.id;
  for (const key of ['--custom-bg', '--custom-accent', '--custom-accent-2']) root.style.removeProperty(key);
  if (themeState.id === 'custom') {
    root.style.setProperty('--custom-bg', themeState.custom.bg);
    root.style.setProperty('--custom-accent', themeState.custom.accent);
    root.style.setProperty('--custom-accent-2', themeState.custom.accent2);
  }
  saveTheme();
  refreshPalette();
  syncThemeSelect();
  drawWave();
  requestDraw();
}

function openThemeModal() {
  const presets = THEMES.filter((t) => t.id !== 'custom').map((t) => `
    <button type="button" class="theme-preset ${t.id === themeState.id ? 'active' : ''}" data-theme-id="${t.id}">
      <span class="theme-swatches">${t.swatches.map((c) => `<i style="background:${c}"></i>`).join('')}</span>
      <b>${t.name}</b><span>${t.note}</span>
    </button>`).join('');
  openModal('Studio theme', `
    <p>Pick a preset or mix your own three colours. Stored in this browser only.</p>
    <div class="theme-presets">${presets}</div>
    <div class="theme-custom">
      <h3>Custom colours</h3>
      <div class="two-col">
        <label class="field">Background<input id="thBg" type="color" value="${themeState.custom.bg}"></label>
        <label class="field">Accent<input id="thAccent" type="color" value="${themeState.custom.accent}"></label>
      </div>
      <div class="two-col">
        <label class="field">Highlight<input id="thAccent2" type="color" value="${themeState.custom.accent2}"></label>
        <label class="field">Default preset<input value="Asuka Soryu" disabled></label>
      </div>
    </div>
    <div class="theme-actions">
      <button id="thApply" class="primary">Use custom</button>
      <button id="thReset" class="tiny ghost">Reset to Asuka Soryu</button>
    </div>
  `);
  $$('.theme-preset').forEach((btn) => {
    btn.onclick = () => { applyTheme(btn.dataset.themeId); closeModal(); };
  });
  $('#thApply').onclick = () => {
    applyTheme('custom', {
      bg: $('#thBg').value,
      accent: $('#thAccent').value,
      accent2: $('#thAccent2').value,
    });
    closeModal();
  };
  $('#thReset').onclick = () => {
    themeState.custom = { ...CUSTOM_DEFAULTS };
    applyTheme('asuka');
    closeModal();
  };
}


const beatToX = (b) => GUTTER + (b - S.scrollBeat) * ppb();
const xToBeat = (x) => (x - GUTTER) / ppb() + S.scrollBeat;
const midiToY = (m) => RULER + (S.topMidi - m) * noteH();
const yToMidi = (y) => S.topMidi - (y - RULER) / noteH();

/* ------------------------------------------------------------------ utils */
function toast(msg, kind = '', ms = 3400) {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $('#toastWrap').appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(5px)';
    setTimeout(() => el.remove(), 320);
  }, ms);
}

async function api(path, opts = {}) {
  const options = { ...opts };
  if (options.body && !(options.body instanceof FormData)) {
    options.headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (typeof options.body !== 'string') options.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, options);
  const ct = res.headers.get('content-type') || '';
  const data = ct.includes('json') ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || res.statusText || 'Request failed');
  return data;
}

function openModal(title, html) {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = html;
  $('#modal').classList.remove('hidden');
}
function closeModal() {
  $('#modal').classList.add('hidden');
  if (typeof syncThemeSelect === 'function') syncThemeSelect();
}
$('#modalClose').onclick = closeModal;
$('#modal').addEventListener('pointerdown', (e) => { if (e.target.id === 'modal') closeModal(); });

/* ------------------------------------------------------------------ audio */
let audioCtx = null;
function previewTone(midi, dur = 0.5) {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const t = audioCtx.currentTime;
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'triangle';
    osc.frequency.value = midiToHz(midi);
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.16, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0005, t + dur);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(t);
    osc.stop(t + dur + 0.05);
  } catch (err) { /* ignore */ }
}

S.audio.addEventListener('timeupdate', () => {
  S.playheadBeat = S.audio.currentTime / spb();
  updateTime();
  requestDraw();
});
S.audio.addEventListener('play', () => { S.playing = true; updateTransport(); schedulePlaybackDraw(); });
S.audio.addEventListener('pause', () => { S.playing = false; updateTransport(); requestDraw(); });
S.audio.addEventListener('ended', () => {
  S.playing = false;
  updateTransport();
  if (S.playAfter) S.playAfter = false;
  requestDraw();
});
S.audio.addEventListener('error', () => {
  S.playing = false;
  updateTransport();
});

const spb = () => (S.project ? 60 / S.project.bpm : 0.5);

let playRaf = null;
function schedulePlaybackDraw() {
  if (playRaf) return;
  const tick = () => {
    playRaf = null;
    if (!S.playing) return;
    const beat = S.audio.currentTime / spb();
    S.playheadBeat = beat;
    updateTime();
    if (beat * ppb() + GUTTER > wrap.clientWidth - 60) {
      S.scrollBeat = beat - (wrap.clientWidth - GUTTER - 120) / ppb();
    }
    requestDraw();
    playRaf = requestAnimationFrame(tick);
  };
  playRaf = requestAnimationFrame(tick);
}

function updateTime() {
  $('#timeDisplay').textContent = fmtTime(S.audio.currentTime || S.playheadBeat * spb());
  const dur = S.audio.duration || 0;
  const frac = dur > 0 ? S.audio.currentTime / dur : 0;
  $('#waveplay').style.left = `${clamp(frac, 0, 1) * 100}%`;
}

function updateTransport() {
  $('#btnPlay .ico-play').classList.toggle('hidden', S.playing);
  $('#btnPlay .ico-pause').classList.toggle('hidden', !S.playing);
  const dot = $('#statusDot');
  dot.className = 'dot' + (S.playing ? ' ok' : '');
}

/* ------------------------------------------------------------------ draw */
let drawRaf = null;
function requestDraw() {
  if (drawRaf != null) return;
  drawRaf = requestAnimationFrame(() => { drawRaf = null; drawRoll(); });
}

function resizeCanvas(c, context) {
  const rect = c.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  if (c.width !== Math.floor(w * dpr) || c.height !== Math.floor(h * dpr)) {
    c.width = Math.floor(w * dpr);
    c.height = Math.floor(h * dpr);
  }
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w, h };
}

function drawRoll() {
  if (!S.project) return;
  const { w, h } = resizeCanvas(canvas, ctx);
  ctx.clearRect(0, 0, w, h);
  const nh = noteH();

  // background
  const bg = ctx.createLinearGradient(0, 0, 0, h);
  bg.addColorStop(0, TP.rollBg);
  bg.addColorStop(1, TP.rollBg2);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  const lowMidi = Math.floor(yToMidi(h));
  const highMidi = Math.ceil(yToMidi(RULER));

  // scale rows: highlight notes in the selected key (very subtle)
  const keyRoot = keyRootPc();
  for (let m = lowMidi; m <= highMidi; m++) {
    const y = midiToY(m);
    const pc = ((m % 12) + 12) % 12;
    const black = [1, 3, 6, 8, 10].includes(pc);
    ctx.fillStyle = black ? TP.rowBlack : TP.rowWhite;
    ctx.fillRect(GUTTER, y, w - GUTTER, nh);
    if (pc === keyRoot) {
      ctx.fillStyle = TP.rowKey;
      ctx.fillRect(GUTTER, y, w - GUTTER, nh);
    }
    ctx.strokeStyle = TP.lineSoft;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(GUTTER, y + nh);
    ctx.lineTo(w, y + nh);
    ctx.stroke();
  }

  // beat grid
  const beatsPerBar = S.project.timeSignature[0] || 4;
  const first = Math.floor(S.scrollBeat);
  const last = Math.ceil(xToBeat(w));
  for (let b = first; b <= last; b++) {
    const x = beatToX(b);
    if (x < GUTTER - 1) continue;
    const bar = b % beatsPerBar === 0;
    ctx.strokeStyle = bar ? TP.bar : TP.grid;
    ctx.lineWidth = bar ? 1.5 : 1;
    ctx.beginPath();
    ctx.moveTo(x, RULER);
    ctx.lineTo(x, h);
    ctx.stroke();
    if (bar) {
      const num = Math.floor(b / beatsPerBar) + 1;
      ctx.fillStyle = TP.text;
      ctx.font = '10px "Cascadia Mono", Consolas, monospace';
      ctx.fillText(String(num), x + 4, 12);
    }
  }

  // ruler strip
  ctx.fillStyle = TP.ruler;
  ctx.fillRect(GUTTER, 0, w - GUTTER, RULER);
  ctx.strokeStyle = TP.rulerLine;
  ctx.beginPath();
  ctx.moveTo(GUTTER, RULER + 0.5);
  ctx.lineTo(w, RULER + 0.5);
  ctx.stroke();

  // loop region
  const loop = S.project.loop || { start: 0, end: 16 };
  if (loop.end > loop.start) {
    ctx.fillStyle = hexA(TP.accent2, 0.07);
    ctx.fillRect(beatToX(loop.start), RULER, (loop.end - loop.start) * ppb(), h - RULER);
    ctx.fillStyle = hexA(TP.accent2, 0.75);
    ctx.fillRect(beatToX(loop.start), 0, 2, RULER);
    ctx.fillRect(beatToX(loop.end) - 2, 0, 2, RULER);
  }

  // notes
  const tracks = S.project.tracks || [];
  tracks.forEach((track, ti) => {
    const color = track.color || TRACK_COLORS[ti % TRACK_COLORS.length];
    for (const note of track.notes || []) {
      if (note.start > last + 1 || note.start + note.dur < first - 1) continue;
      if (note.midi < lowMidi - 1 || note.midi > highMidi + 1) continue;
      drawNote(note, track, ti, color);
    }
  });

  // piano gutter
  ctx.fillStyle = TP.keyBlack;
  ctx.fillRect(0, 0, GUTTER, h);
  ctx.strokeStyle = TP.line;
  ctx.beginPath();
  ctx.moveTo(GUTTER - 0.5, 0);
  ctx.lineTo(GUTTER - 0.5, h);
  ctx.stroke();
  for (let m = lowMidi; m <= highMidi; m++) {
    const y = midiToY(m);
    const pc = ((m % 12) + 12) % 12;
    const black = [1, 3, 6, 8, 10].includes(pc);
    if (black) {
      ctx.fillStyle = TP.keyBlack;
      ctx.fillRect(0, y, GUTTER - 14, nh);
    } else {
      ctx.fillStyle = TP.keyWhite;
      ctx.fillRect(0, y, GUTTER - 14, nh - 1);
    }
    if (pc === 0) {
      ctx.fillStyle = black ? TP.keyLabel : TP.noteInk;
      ctx.font = '9px "Cascadia Mono", Consolas, monospace';
      ctx.fillText(`C${Math.floor(m / 12) - 1}`, 4, y + nh - 3);
    }
  }

  // selection marquee
  if (S.marquee) {
    const { x0, y0, x1, y1 } = S.marquee;
    ctx.fillStyle = hexA(TP.accent, 0.14);
    ctx.strokeStyle = hexA(TP.accent, 0.85);
    ctx.lineWidth = 1;
    const rx = Math.min(x0, x1), ry = Math.min(y0, y1);
    ctx.fillRect(rx, ry, Math.abs(x1 - x0), Math.abs(y1 - y0));
    ctx.strokeRect(rx, ry, Math.abs(x1 - x0), Math.abs(y1 - y0));
  }

  // playhead
  const beat = S.playing || S.audio.currentTime > 0 ? S.audio.currentTime / spb() : S.playheadBeat;
  const px = beatToX(beat);
  if (px > GUTTER - 2 && px < w + 2) {
    ctx.fillStyle = hexA(TP.playhead, 0.14);
    ctx.fillRect(px - 3, 0, 6, h);
    ctx.strokeStyle = TP.playhead;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px + 0.5, 0);
    ctx.lineTo(px + 0.5, h);
    ctx.stroke();
    ctx.fillStyle = TP.playhead;
    ctx.fillRect(px - 4, 0, 8, 3);
  }

  ctx.fillStyle = TP.ruler;
  ctx.fillRect(0, 0, GUTTER, RULER);
  ctx.fillStyle = TP.keyLabel;
  ctx.font = '9px "Cascadia Mono", Consolas, monospace';
  ctx.fillText('KEYS', 8, 12);
}

function keyRootPc() {
  const key = (S.project && S.project.key) || 'C major';
  const map = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
  let root = map[key[0]] ?? 0;
  if (key[1] === 'b') root = (root + 11) % 12;
  if (key[1] === '#') root = (root + 1) % 12;
  return root;
}

function drawNote(note, track, ti, color) {
  const x = beatToX(note.start);
  const w = Math.max(5, note.dur * ppb() - 2);
  const y = midiToY(note.midi);
  const h = noteH() - 2;
  if (y + h < RULER || y > canvas.clientHeight) return;
  const selected = S.selection.has(note.id);
  const active = ti === S.activeTrack;
  const alpha = track.muted ? 0.28 : active ? 0.9 : 0.62;

  ctx.save();
  const r = Math.min(2, h / 2);
  roundedRect(ctx, x + 1, y + 1, w, h, r);
  ctx.fillStyle = hexA(color, alpha);
  ctx.fill();

  // velocity strip
  ctx.fillStyle = hexA('#ffffff', 0.06 + note.velocity * 0.12);
  ctx.fillRect(x + 2, y + h - 2.5, Math.max(0, w - 2) * (note.velocity || 0.8), 1.5);

  if (selected) {
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    roundedRect(ctx, x + 1, y + 1, w, h, r);
    ctx.stroke();
  } else {
    ctx.strokeStyle = hexA(TP.noteInk, 0.55);
    ctx.lineWidth = 1;
    roundedRect(ctx, x + 1, y + 1, w, h, r);
    ctx.stroke();
  }

  if (w > 16) {
    ctx.beginPath();
    ctx.rect(x + 3, y, w - 6, h);
    ctx.clip();
    ctx.fillStyle = selected ? '#ffffff' : hexA(TP.noteInk, 0.92);
    ctx.font = `700 ${Math.min(11, Math.max(8, h - 6))}px "Segoe UI", Tahoma, sans-serif`;
    ctx.textBaseline = 'middle';
    ctx.fillText(note.lyric || '', x + 5, y + h / 2 + 0.5);
    if (w > 58) {
      ctx.fillStyle = hexA(TP.noteInk, selected ? 0.75 : 0.6);
      ctx.font = `8px "Cascadia Mono", Consolas, monospace`;
      const name = midiToName(note.midi);
      const tw = ctx.measureText(note.lyric || '').width;
      ctx.fillText(name, x + Math.min(w - 20, 8 + tw), y + h / 2 + 0.5);
    }
  }
  ctx.restore();
}

function roundedRect(c, x, y, w, h, r) {
  c.beginPath();
  c.moveTo(x + r, y);
  c.arcTo(x + w, y, x + w, y + h, r);
  c.arcTo(x + w, y + h, x, y + h, r);
  c.arcTo(x, y + h, x, y, r);
  c.arcTo(x, y, x + w, y, r);
  c.closePath();
}

const _probe = document.createElement('span');
_probe.style.display = 'none';
document.body.appendChild(_probe);
const _rgbCache = new Map();

/* Resolve any CSS colour (hex, rgb(), color-mix(), var-derived) to "r,g,b". */
function colorParts(color) {
  const key = String(color);
  if (_rgbCache.has(key)) return _rgbCache.get(key);
  let text = key;
  if (!/^rgba?\(/i.test(text)) {
    _probe.style.color = '';
    _probe.style.color = text;
    text = getComputedStyle(_probe).color || text;
  }
  const m = text.match(/rgba?\(([^)]+)\)/i);
  let parts = [255, 255, 255, 1];
  if (m) {
    const nums = m[1].split(/[,/\s]+/).filter(Boolean).map(Number);
    if (nums.length >= 3 && nums.slice(0, 3).every((n) => Number.isFinite(n))) {
      parts = [nums[0], nums[1], nums[2], Number.isFinite(nums[3]) ? nums[3] : 1];
    }
  } else {
    const srgb = text.match(/color\(srgb\s+([^)]+)\)/i);
    if (srgb) {
      const nums = srgb[1].split(/[,/\s]+/).filter(Boolean).map(Number);
      if (nums.length >= 3 && nums.slice(0, 3).every((n) => Number.isFinite(n))) {
        parts = [
          Math.round(clamp(nums[0], 0, 1) * 255),
          Math.round(clamp(nums[1], 0, 1) * 255),
          Math.round(clamp(nums[2], 0, 1) * 255),
          Number.isFinite(nums[3]) ? nums[3] : 1,
        ];
      }
    }
  }
  _rgbCache.set(key, parts);
  return parts;
}

function hexA(color, a) {
  const [r, g, b] = colorParts(color);
  return `rgba(${r},${g},${b},${a})`;
}

/* Turn a token into a concrete rgba() string so <canvas> never sees color-mix(). */
function resolveColor(raw, fallback) {
  const [r, g, b, a] = colorParts(raw || fallback);
  return `rgba(${r},${g},${b},${a})`;
}

/* ------------------------------------------------------------------ wave */
function drawWave() {
  const { w, h } = resizeCanvas(waveCanvas, wctx);
  wctx.clearRect(0, 0, w, h);
  wctx.fillStyle = TP.waveBg || cssVar('--wave-bg', '#0f0909');
  wctx.fillRect(0, 0, w, h);

  // mid line
  wctx.strokeStyle = TP.waveLine || cssVar('--wave-line', '#2c1a18');
  wctx.beginPath();
  wctx.moveTo(0, h / 2);
  wctx.lineTo(w, h / 2);
  wctx.stroke();

  const meta = S.render;
  if (!meta || !meta.peaks || !meta.peaks.length) {
    wctx.fillStyle = TP.waveText || cssVar('--wave-text', '#6c4f47');
    wctx.font = '10px "Cascadia Mono", Consolas, monospace';
    wctx.textAlign = 'center';
    wctx.fillText('render to see the waveform', w / 2, h / 2 - 8);
    wctx.textAlign = 'left';
    return;
  }
  const peaks = meta.peaks;
  const n = peaks.length;
  const barW = w / n;
  wctx.fillStyle = TP.accent;
  for (let i = 0; i < n; i++) {
    const [lo, hi] = peaks[i];
    const y1 = h / 2 - hi * (h / 2 - 4);
    const y2 = h / 2 - lo * (h / 2 - 4);
    wctx.fillRect(i * barW, y1, Math.max(0.6, barW - 0.4), Math.max(1, y2 - y1));
  }
  // ticks per second
  wctx.fillStyle = TP.waveText || cssVar('--wave-text', '#6c4f47');
  wctx.font = '8px "Cascadia Mono", Consolas, monospace';
  const dur = meta.duration || 0;
  const step = dur > 25 ? 5 : dur > 12 ? 2 : 1;
  for (let t = step; t < dur; t += step) {
    const x = (t / dur) * w;
    const label = `${Math.round(t)}s`;
    wctx.fillRect(x, h - 4, 1, 3);
    if (w / step > 70) wctx.fillText(label, x + 2, h - 6);
  }
}

/* ------------------------------------------------------------------ project */
async function loadState(first = true) {
  try {
    const st = await api('/api/state');
    S.voices = st.voices || [];
    S.projects = st.projects || [];
    S.rvc = st.rvc || {};
    S.engine = st.engine || {};
    renderVoices();
    renderRvc();
    renderProjectSelect();
    renderHostFeature();

    if (st.rvc && st.rvc.probing) setTimeout(refreshRvc, 1800);

    if (first) {
      if (S.projects.length) {
        await openProject(S.projects[0].id);
      } else {
        setProject(st.defaultProject, null);
      }
    }
  } catch (err) {
    toast(`Cannot reach the server: ${err.message}`, 'error', 8000);
  }
}

async function refreshRvc() {
  try {
    const st = await api('/api/rvc');
    S.rvc = st;
    renderRvc();
    if (st.probing) setTimeout(refreshRvc, 2000);
  } catch (err) { /* ignore */ }
}

function setProject(project, id) {
  S.project = project;
  S.projectId = id || null;
  S.selection.clear();
  S.activeTrack = 0;
  S.render = null;
  S.playheadBeat = 0;
  S.audio.pause();
  S.audio.removeAttribute('src');
  S.audioMode = 'final';
  $('#renderBadge').classList.add('hidden');
  $('#btnExport').disabled = true;
  $('#btnCompare').disabled = true;
  $('#waveplay').style.left = '0%';
  $('#renderMeta').textContent = '';
  $('#renderBar').style.width = '0%';
  $('#renderStatus').textContent = 'No render yet';
  $('#renderLog').classList.add('hidden');

  if (!S.project.voice) S.project.voice = {};
  syncAllControls();
  renderTracks();
  renderVoiceSelect();
  fitView();
  updateUndoButtons();
  refreshEmptyState();
  drawWave();
  requestDraw();
  S.dirty = false;
}

function refreshEmptyState() {
  const count = (S.project?.tracks || []).reduce((a, t) => a + (t.notes?.length || 0), 0);
  $('#rollEmpty').classList.toggle('hidden', count > 0);
}

function updateSnap() {
  const sel = $('#snapSel');
  if (sel) S.snap = parseFloat(sel.value) || 0.25;
}

function fitView() {
  const tracks = S.project.tracks || [];
  const notes = tracks.flatMap((t) => t.notes || []);
  let maxBeat = 16;
  let minMidi = 55;
  let maxMidi = 76;
  if (notes.length) {
    maxBeat = Math.max(...notes.map((n) => n.start + n.dur), 8);
    minMidi = Math.min(...notes.map((n) => n.midi));
    maxMidi = Math.max(...notes.map((n) => n.midi));
  }
  const width = Math.max(400, wrap.clientWidth - GUTTER - 20);
  S.zoom = clamp(width / (Math.max(8, maxBeat) * BASE_PPB), 0.35, 2);
  S.scrollBeat = 0;
  S.topMidi = clamp(maxMidi + 3, 36, 104);
  $('#zoomLabel').textContent = `${Math.round(S.zoom * 100)}%`;
  updateSnap();
}

async function openProject(id) {
  try {
    const data = await api(`/api/projects?id=${encodeURIComponent(id)}`);
    setProject(data.project, id);
    renderProjectSelect();
    toast('Project loaded', 'ok', 1600);
  } catch (err) {
    toast(err.message, 'error');
  }
}

async function saveProject(silent = false) {
  if (!S.project) return;
  S.project.name = $('#projectName').value.trim() || 'Untitled';
  S.project.bpm = clamp(parseFloat($('#bpm').value) || 120, 20, 300);
  S.project.key = $('#keySel').value;
  try {
    const res = await api('/api/projects', {
      method: 'POST',
      body: { id: S.projectId, project: S.project },
    });
    S.projectId = res.id;
    S.project = res.project;
    S.project.id = res.id;
    S.dirty = false;
    const st = await api('/api/projects');
    S.projects = st.projects || [];
    renderProjectSelect();
    if (!silent) toast('Project saved', 'ok', 1800);
  } catch (err) {
    toast(`Save failed: ${err.message}`, 'error');
  }
}

async function deleteProject(id) {
  try {
    await api(`/api/projects?id=${encodeURIComponent(id)}`, { method: 'DELETE' });
    const st = await api('/api/projects');
    S.projects = st.projects || [];
    renderProjectSelect();
    if (S.projectId === id) {
      S.projectId = null;
      setProject({ ...S.project, id: uid('prj') }, null);
      S.dirty = true;
    }
    toast('Project deleted', 'ok', 1600);
  } catch (err) {
    toast(err.message, 'error');
  }
}

function renderProjectSelect() {
  const sel = $('#projectSelect');
  sel.innerHTML = '';
  const cur = document.createElement('option');
  cur.value = '__current';
  cur.textContent = 'current project';
  sel.appendChild(cur);
  for (const p of S.projects) {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    if (p.id === S.projectId) opt.selected = true;
    sel.appendChild(opt);
  }
  const sep = document.createElement('option');
  sep.disabled = true;
  sep.textContent = '──────────';
  sel.appendChild(sep);
  const demo = document.createElement('option');
  demo.value = '__demo';
  demo.textContent = 'Load demo song';
  sel.appendChild(demo);
  const fresh = document.createElement('option');
  fresh.value = '__new';
  fresh.textContent = 'New empty project';
  sel.appendChild(fresh);
}

/* ------------------------------------------------------------------ tracks */
function renderTracks() {
  const host = $('#trackList');
  host.innerHTML = '';
  (S.project.tracks || []).forEach((track, i) => {
    const item = document.createElement('div');
    item.className = 'track-item' + (i === S.activeTrack ? ' active' : '');
    item.onclick = (e) => {
      if (e.target.closest('button') || e.target.tagName === 'INPUT') return;
      S.activeTrack = i;
      renderTracks();
      requestDraw();
    };

    const top = document.createElement('div');
    top.className = 'track-top';

    const dot = document.createElement('span');
    dot.className = 'track-dot';
    dot.style.background = track.color || TRACK_COLORS[i % TRACK_COLORS.length];

    const name = document.createElement('input');
    name.className = 'track-name-input';
    name.value = track.name;
    name.onchange = () => { track.name = name.value || `Track ${i + 1}`; S.dirty = true; };

    const mute = document.createElement('button');
    mute.className = 'track-mute' + (track.muted ? ' on' : '');
    mute.textContent = track.muted ? 'M' : 'M';
    mute.title = 'Mute track';
    mute.onclick = () => { track.muted = !track.muted; S.dirty = true; renderTracks(); requestDraw(); };

    const del = document.createElement('button');
    del.className = 'track-del';
    del.textContent = '×';
    del.title = 'Delete track';
    del.onclick = () => {
      if (S.project.tracks.length === 1) { toast('Keep at least one track'); return; }
      if (!confirm(`Delete track “${track.name}”?`)) return;
      S.project.tracks.splice(i, 1);
      S.activeTrack = clamp(S.activeTrack, 0, S.project.tracks.length - 1);
      S.dirty = true;
      renderTracks();
      refreshEmptyState();
      requestDraw();
    };

    top.append(dot, name, mute, del);

    const mix = document.createElement('div');
    mix.className = 'track-mix';
    const lbl = document.createElement('span');
    lbl.textContent = 'VOL';
    const range = document.createElement('input');
    range.type = 'range';
    range.min = '0'; range.max = '150'; range.step = '1';
    range.value = String(Math.round((track.gain ?? 1) * 100));
    const val = document.createElement('span');
    val.textContent = `${range.value}%`;
    range.oninput = () => {
      track.gain = parseInt(range.value, 10) / 100;
      val.textContent = `${range.value}%`;
      S.dirty = true;
    };
    mix.append(lbl, range, val);

    item.append(top, mix);
    host.appendChild(item);
  });
}

function addTrack() {
  const i = S.project.tracks.length;
  S.project.tracks.push({
    id: uid('trk'),
    name: `Track ${i + 1}`,
    gain: 1.0,
    pan: 0,
    muted: false,
    color: TRACK_COLORS[i % TRACK_COLORS.length],
    notes: [],
  });
  S.activeTrack = i;
  S.dirty = true;
  renderTracks();
  requestDraw();
}

/* ------------------------------------------------------------------ voices */
function renderVoices() {
  const host = $('#voiceList');
  host.innerHTML = '';
  if (!S.voices.length) {
    host.innerHTML = '<div class="emptystate">No voicebanks yet.<br>Drop a RVC <b>.pth</b> below, or use the DSP singer.</div>';
  } else {
    for (const v of S.voices) {
      const item = document.createElement('div');
      item.className = 'voice-item' + (S.project?.voice?.id === v.id ? ' active' : '');
      item.onclick = (e) => {
        if (e.target.closest('button')) return;
        selectVoice(v.id);
      };
      const av = document.createElement('div');
      av.className = 'voice-avatar';
      av.textContent = (v.name || 'V').trim().slice(0, 2).toUpperCase();
      av.style.background = v.color || '#d81f2a';
      const main = document.createElement('div');
      main.className = 'voice-main';
      const nm = document.createElement('div');
      nm.className = 'voice-name';
      nm.textContent = v.name;
      const sub = document.createElement('div');
      sub.className = 'voice-sub';
      sub.textContent = `${(v.size / 1048576).toFixed(0)} MB${v.index ? ' · index' : ''}${S.project?.voice?.id === v.id ? ' · selected' : ''}`;
      main.append(nm, sub);
      const actions = document.createElement('div');
      actions.className = 'voice-actions';
      const del = document.createElement('button');
      del.title = 'Delete voicebank';
      del.textContent = '🗑';
      del.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete voicebank “${v.name}” from disk?`)) return;
        try {
          await api(`/api/voices?id=${encodeURIComponent(v.id)}`, { method: 'DELETE' });
          S.voices = (await api('/api/voices')).voices;
          if (S.project.voice.id === v.id) S.project.voice.id = null;
          renderVoices();
          renderVoiceSelect();
        } catch (err) { toast(err.message, 'error'); }
      };
      actions.append(del);
      item.append(av, main, actions);
      host.appendChild(item);
    }
  }
  renderVoiceSelect();
}

function selectVoice(id) {
  S.project.voice.id = id || null;
  S.dirty = true;
  renderVoices();
  const v = S.voices.find((x) => x.id === id);
  $('#voiceHint').textContent = v
    ? `Singing with “${v.name}”. ${v.index ? 'FAISS index found — nice.' : 'No index file; timbre will be flatter.'}`
    : 'Pick a voicebank to sing with your own RVC model.';
  requestDraw();
}

function renderVoiceSelect() {
  const sel = $('#voiceSelect');
  sel.innerHTML = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '— DSP singer (no RVC) —';
  sel.appendChild(none);
  for (const v of S.voices) {
    const opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.name;
    sel.appendChild(opt);
  }
  sel.value = S.project?.voice?.id || '';
}

function renderHostFeature() {
  const link = $('#linkVoiceLab');
  if (!link) return;
  const hosted = (S.engine && S.engine.server) === 'gradio+fastapi';
  link.classList.toggle('hidden', !hosted);
}

function renderRvc() {
  const chip = $('#rvcChip');
  const info = $('#rvcInfo');
  const r = S.rvc || {};
  if (r.probing) {
    chip.className = 'chip busy';
    chip.textContent = 'checking…';
    info.textContent = 'Probing the RVC environment…';
    return;
  }
  if (r.available) {
    chip.className = 'chip ok';
    chip.textContent = r.device === 'cuda' ? 'RVC · GPU' : 'RVC · CPU';
    info.innerHTML = `Torch ${r.torch || '?'} · ${r.device || 'cpu'}<br>RMVPE ${r.rmvpe ? 'ready' : 'missing'} · ContentVec ${r.contentvec ? 'ready' : 'auto-download'}`;
  } else {
    chip.className = 'chip bad';
    chip.textContent = 'not installed';
    info.textContent = r.reason || 'RVC environment is not available.';
  }
}

/* ------------------------------------------------------------------ voice controls */
const SLIDERS = [
  { key: 'vibratoDepth', id: 'vibratoDepth', label: 'v_vibratoDepth', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)} ct` },
  { key: 'vibratoRate', id: 'vibratoRate', label: 'v_vibratoRate', toUi: (v) => v, fromUi: (v) => v, fmt: (v) => `${(+v).toFixed(1)} Hz` },
  { key: 'scoop', id: 'scoop', label: 'v_scoop', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)} ct` },
  { key: 'breathiness', id: 'breathiness', label: 'v_breathiness', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: 'brightness', id: 'brightness', label: 'v_brightness', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: 'formantShift', id: 'formantShift', label: 'v_formantShift', toUi: (v) => v, fromUi: (v) => v, fmt: (v) => (+v).toFixed(2) },
  { key: 'dynamics', id: 'dynamics', label: 'v_dynamics', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: 'jitter', id: 'jitter', label: 'v_jitter', toUi: (v) => v * 1000, fromUi: (v) => v / 1000, fmt: (v) => `${(+v * 1000).toFixed(1)}‰` },
  { key: 'indexRate', id: 'indexRate', label: 'v_indexRate', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: 'protect', id: 'protect', label: 'v_protect', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => (+v).toFixed(2) },
  { key: 'reverb', id: 'reverb', label: 'v_reverb', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
  { key: 'gain', id: 'gain', label: 'v_gain', toUi: (v) => v * 100, fromUi: (v) => v / 100, fmt: (v) => `${Math.round(v * 100)}%` },
];

function initSliders() {
  for (const conf of SLIDERS) {
    const el = document.getElementById(conf.id);
    if (!el) continue;
    el.addEventListener('input', () => {
      S.project.voice[conf.key] = conf.fromUi(parseFloat(el.value));
      updateSliderLabel(conf);
      S.dirty = true;
    });
  }
}

function updateSliderLabel(conf) {
  const val = S.project?.voice?.[conf.key];
  const lbl = document.getElementById(conf.label);
  if (lbl && val != null) lbl.textContent = conf.fmt(val);
}

function syncAllControls() {
  const v = S.project.voice;
  for (const conf of SLIDERS) {
    const el = document.getElementById(conf.id);
    if (!el) continue;
    const val = v[conf.key];
    if (val != null) el.value = String(conf.toUi(val));
    updateSliderLabel(conf);
  }
  $('#pitchShift').value = S.project.voice.pitch ?? 0;
  $('#speakerId').value = S.project.voice.sid ?? 0;
  $('#f0Method').value = S.project.voice.f0Method || 'rmvpe';
  $('#compressor').checked = S.project.voice.compressor !== false;
  $('#projectName').value = S.project.name || 'Untitled';
  $('#bpm').value = S.project.bpm || 120;
  $('#keySel').value = S.project.key || 'C major';
  $('#voiceSelect').value = v.id || '';
}

$('#voiceSelect').onchange = (e) => selectVoice(e.target.value);
$('#modeSel').onchange = () => {};
$('#pitchShift').onchange = (e) => { S.project.voice.pitch = clamp(parseInt(e.target.value, 10) || 0, -24, 24); S.dirty = true; };
$('#speakerId').onchange = (e) => { S.project.voice.sid = Math.max(0, parseInt(e.target.value, 10) || 0); S.dirty = true; };
$('#f0Method').onchange = (e) => { S.project.voice.f0Method = e.target.value; S.dirty = true; };
$('#compressor').onchange = (e) => { S.project.voice.compressor = e.target.checked; S.dirty = true; };
$('#projectName').onchange = (e) => { S.project.name = e.target.value.trim() || 'Untitled'; S.dirty = true; };
$('#bpm').onchange = (e) => {
  S.project.bpm = clamp(parseFloat(e.target.value) || 120, 20, 300);
  e.target.value = S.project.bpm;
  S.dirty = true;
  requestDraw();
};
$('#keySel').onchange = (e) => { S.project.key = e.target.value; S.dirty = true; requestDraw(); };

$('#btnResetExpr').onclick = () => {
  Object.assign(S.project.voice, {
    vibratoDepth: 0.2, vibratoRate: 5.6, scoop: 0.12, breathiness: 0.12,
    brightness: 0.55, formantShift: 1.0, dynamics: 0.5, jitter: 0.006,
  });
  syncAllControls();
  S.dirty = true;
};

/* ------------------------------------------------------------------ note selection */
function allNotes() {
  const out = [];
  (S.project?.tracks || []).forEach((track, ti) => {
    for (const note of track.notes || []) out.push({ note, track, ti });
  });
  return out;
}

function selectedEntries() {
  return allNotes().filter((e) => S.selection.has(e.note.id));
}

function selectOnly(note, ti) {
  S.selection.clear();
  if (note) {
    S.selection.add(note.id);
    S.activeTrack = ti ?? S.activeTrack;
  }
  updateSelectionUI();
  renderTracks();
}

function toggleSelect(note, ti) {
  if (S.selection.has(note.id)) S.selection.delete(note.id);
  else { S.selection.add(note.id); S.activeTrack = ti; }
  updateSelectionUI();
  renderTracks();
}

function updateSelectionUI() {
  const entries = selectedEntries();
  const count = entries.length;
  $('#selCount').textContent = count === 0 ? 'none' : count === 1 ? '1 note' : `${count} notes`;
  const panel = $('#notePanel');
  panel.classList.toggle('disabled', count === 0);
  if (!count) {
    $('#notePitchName').textContent = '—';
    $('#noteMidi').textContent = '—';
    $('#phoneChips').innerHTML = '';
    $('#phoneHint').textContent = '—';
    return;
  }
  const first = entries[0].note;
  $('#notePitchName').textContent = midiToName(first.midi);
  $('#noteMidi').textContent = `MIDI ${first.midi}`;
  $('#noteLyric').value = first.lyric || '';
  $('#noteStart').value = first.start;
  $('#noteDur').value = first.dur;
  $('#noteVel').value = Math.round((first.velocity ?? 0.82) * 100);
  $('#noteVelVal').textContent = Math.round((first.velocity ?? 0.82) * 100);
  ['noteStart', 'noteDur'].forEach((id) => { document.getElementById(id).disabled = count > 1; });
  updatePhonemes(first);
  requestDraw();
}

function updatePhonemes(note) {
  const token = ++S.phoneToken;
  const lyric = note.lyric || '';
  if (!lyric) { $('#phoneChips').innerHTML = ''; $('#phoneHint').textContent = 'rest'; return; }
  const q = new URLSearchParams({
    text: lyric, midi: String(note.midi), dur: String(note.dur), bpm: String(S.project.bpm),
  });
  api(`/api/g2p?${q}`).then((data) => {
    if (token !== S.phoneToken) return;
    const chips = $('#phoneChips');
    chips.innerHTML = '';
    const phones = (data.note && data.note.phones) || [];
    if (!phones.length) {
      chips.innerHTML = '<span class="phone-chip">?</span>';
      return;
    }
    for (const p of phones) {
      const chip = document.createElement('span');
      chip.className = 'phone-chip';
      chip.innerHTML = `<b>${p.phone}</b><small>${Math.round((p.end - p.start) * 1000)}ms</small>`;
      chips.appendChild(chip);
    }
    $('#phoneHint').textContent = data.words?.[0]?.phones?.join(' ') || '';
  }).catch(() => {});
}

$('#noteLyric').addEventListener('input', (e) => {
  const lyric = e.target.value;
  S.lastLyric = lyric;
  for (const { note } of selectedEntries()) note.lyric = lyric;
  S.dirty = true;
  requestDraw();
  const first = selectedEntries()[0];
  if (first) updatePhonemes(first.note);
});
$('#noteVel').addEventListener('input', (e) => {
  const v = parseInt(e.target.value, 10) / 100;
  $('#noteVelVal').textContent = e.target.value;
  for (const { note } of selectedEntries()) note.velocity = v;
  S.dirty = true;
  requestDraw();
});
$('#noteStart').addEventListener('change', (e) => {
  const entries = selectedEntries();
  if (entries.length !== 1) return;
  entries[0].note.start = Math.max(0, parseFloat(e.target.value) || 0);
  S.dirty = true;
  requestDraw();
});
$('#noteDur').addEventListener('change', (e) => {
  const entries = selectedEntries();
  if (entries.length !== 1) return;
  entries[0].note.dur = Math.max(0.05, parseFloat(e.target.value) || 0.25);
  S.dirty = true;
  requestDraw();
});
$('#btnOctUp').onclick = () => transposeSelected(12);
$('#btnOctDown').onclick = () => transposeSelected(-12);

function transposeSelected(semis) {
  for (const { note } of selectedEntries()) note.midi = clamp(note.midi + semis, 12, 120);
  S.dirty = true;
  updateSelectionUI();
  requestDraw();
}

/* ------------------------------------------------------------------ roll interaction */
function hitTest(x, y) {
  const tracks = S.project.tracks || [];
  for (let ti = tracks.length - 1; ti >= 0; ti--) {
    const track = tracks[ti];
    for (let ni = (track.notes || []).length - 1; ni >= 0; ni--) {
      const note = track.notes[ni];
      const nx = beatToX(note.start);
      const nw = Math.max(5, note.dur * ppb() - 2);
      const ny = midiToY(note.midi);
      const nh = noteH() - 2;
      if (x >= nx && x <= nx + nw && y >= ny && y <= ny + nh) {
        return { note, track, ti, edge: x > nx + nw - 7, nx, nw };
      }
    }
  }
  return null;
}

function localPoint(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  if (e.ctrlKey || e.metaKey) {
    const p = localPoint(e);
    const beatAt = xToBeat(p.x);
    S.zoom = clamp(S.zoom * (e.deltaY < 0 ? 1.12 : 0.89), 0.30, 4);
    S.scrollBeat = Math.max(0, beatAt - (p.x - GUTTER) / ppb());
    $('#zoomLabel').textContent = `${Math.round(S.zoom * 100)}%`;
  } else if (e.shiftKey) {
    S.scrollBeat = Math.max(0, S.scrollBeat + e.deltaY / ppb());
  } else if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    S.topMidi = clamp(S.topMidi + e.deltaY / noteH(), 20, 110);
  } else {
    S.scrollBeat = Math.max(0, S.scrollBeat + e.deltaX / ppb());
  }
  requestDraw();
}, { passive: false });

canvas.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || !S.project) return;
  canvas.setPointerCapture(e.pointerId);
  const { x, y } = localPoint(e);

  if (y < RULER) {
    seekToBeat(xToBeat(x));
    return;
  }
  if (x < GUTTER) {
    const m = Math.round(yToMidi(y));
    if (m > 0) previewTone(m, 0.45);
    return;
  }

  const hit = hitTest(x, y);
  if (hit) {
    if (S.tool === 'erase') {
      removeNotes(new Set([hit.note.id]));
      return;
    }
    if (e.shiftKey) {
      toggleSelect(hit.note, hit.ti);
      return;
    }
    if (!S.selection.has(hit.note.id)) selectOnly(hit.note, hit.ti);
    else S.activeTrack = hit.ti;

    pushUndo();
    const entries = selectedEntries();
    S.drag = {
      mode: hit.edge ? 'resize' : 'move',
      startX: x, startY: y, lastX: x, lastY: y,
      originals: entries.map(({ note }) => ({ id: note.id, start: note.start, dur: note.dur, midi: note.midi })),
      noteId: hit.note.id,
      snapped: null,
    };
    return;
  }

  if (S.tool === 'draw') {
    const beat = snapBeat(xToBeat(x));
    const midi = clamp(Math.round(yToMidi(y)), 12, 120);
    const note = { id: uid(), midi, start: beat, dur: Math.max(S.snap || 0.25, 0.25), lyric: S.defaultLyric || 'la', velocity: 0.82 };
    S.project.tracks[S.activeTrack].notes.push(note);
    selectOnly(note, S.activeTrack);
    S.dirty = true;
    refreshEmptyState();
    requestDraw();
    return;
  }

  // marquee select
  S.marquee = { x0: x, y0: y, x1: x, y1: y, additive: e.shiftKey };
  if (!e.shiftKey) S.selection.clear();
  updateSelectionUI();
});

canvas.addEventListener('pointermove', (e) => {
  if (!S.project) return;
  const { x, y } = localPoint(e);
  if (S.marquee) {
    S.marquee.x1 = x;
    S.marquee.y1 = y;
    requestDraw();
    return;
  }
  if (S.drag) {
    const drag = S.drag;
    if (drag.mode === 'move') {
      let delta = (x - drag.startX) / ppb();
      if (S.snap) delta = Math.round(delta / S.snap) * S.snap;
      const semis = Math.round((drag.startY - y) / noteH());
      for (const orig of drag.originals) {
        const note = findNote(orig.id);
        if (!note) continue;
        note.start = Math.max(0, snapFloor(orig.start + delta));
        note.midi = clamp(orig.midi + semis, 12, 120);
      }
    } else {
      const orig = drag.originals[0];
      const note = findNote(orig.id);
      if (note) {
        let dur = (x - beatToX(orig.start)) / ppb();
        if (S.snap) dur = Math.round(dur / S.snap) * S.snap;
        note.dur = Math.max(S.snap || 0.0625, dur);
      }
    }
    S.dirty = true;
    updateSelectionUI();
    return;
  }
  // hover cursor
  const hit = hitTest(x, y);
  canvas.style.cursor = !hit ? (S.tool === 'draw' ? 'copy' : 'default')
    : hit.edge ? 'ew-resize' : S.tool === 'erase' ? 'not-allowed' : 'grab';
});

canvas.addEventListener('pointerup', (e) => {
  if (S.marquee) {
    const { x0, y0, x1, y1, additive } = S.marquee;
    const rx = Math.min(x0, x1), ry = Math.min(y0, y1);
    const rw = Math.abs(x1 - x0), rh = Math.abs(y1 - y0);
    S.marquee = null;
    if (rw > 4 || rh > 4) {
      if (!additive) S.selection.clear();
      for (const { note, ti } of allNotes()) {
        const nx = beatToX(note.start);
        const nw = Math.max(5, note.dur * ppb());
        const ny = midiToY(note.midi);
        if (nx + nw >= rx && nx <= rx + rw && ny + noteH() >= ry && ny <= ry + rh) {
          S.selection.add(note.id);
        }
      }
      updateSelectionUI();
    }
    requestDraw();
  }
  if (S.drag) {
    S.drag = null;
    updateSelectionUI();
  }
  try { canvas.releasePointerCapture(e.pointerId); } catch (err) { /* noop */ }
});

canvas.addEventListener('dblclick', (e) => {
  const { x, y } = localPoint(e);
  if (x < GUTTER || y < RULER) return;
  const hit = hitTest(x, y);
  if (hit) {
    selectOnly(hit.note, hit.ti);
    openLyricEditor(hit.note);
    return;
  }
  if (S.tool !== 'draw') {
    const beat = snapBeat(xToBeat(x));
    const midi = clamp(Math.round(yToMidi(y)), 12, 120);
    const note = { id: uid(), midi, start: beat, dur: Math.max(S.snap || 0.25, 0.25), lyric: S.defaultLyric || 'la', velocity: 0.82 };
    S.project.tracks[S.activeTrack].notes.push(note);
    S.dirty = true;
    selectOnly(note, S.activeTrack);
    refreshEmptyState();
    openLyricEditor(note);
    requestDraw();
  }
});

function snapBeat(beat) {
  if (!S.snap) return Math.max(0, Math.round(beat * 1000) / 1000);
  return Math.max(0, Math.round(beat / S.snap) * S.snap);
}
function snapFloor(beat) {
  if (!S.snap) return Math.max(0, Math.round(beat * 1000) / 1000);
  return Math.max(0, Math.floor(beat / S.snap + 1e-6) * S.snap);
}

function findNote(id) {
  for (const track of S.project.tracks || []) {
    const n = (track.notes || []).find((x) => x.id === id);
    if (n) return n;
  }
  return null;
}

function removeNotes(ids) {
  if (!ids.size) return;
  pushUndo();
  for (const track of S.project.tracks) {
    track.notes = (track.notes || []).filter((n) => !ids.has(n.id));
  }
  for (const id of ids) S.selection.delete(id);
  S.dirty = true;
  updateSelectionUI();
  refreshEmptyState();
  requestDraw();
}

function seekToBeat(beat) {
  const t = Math.max(0, beat) * spb();
  if (S.audio.src && isFinite(S.audio.duration)) {
    S.audio.currentTime = Math.min(t, S.audio.duration - 0.001);
  }
  S.playheadBeat = Math.max(0, beat);
  updateTime();
  requestDraw();
}

/* ------------------------------------------------------------------ lyric editor */
function openLyricEditor(note) {
  S.editingNote = note.id;
  const ed = $('#lyricEditor');
  const input = $('#lyricEditorInput');
  const x = beatToX(note.start);
  const y = midiToY(note.midi);
  ed.style.left = `${clamp(x + 2, GUTTER, wrap.clientWidth - 130)}px`;
  ed.style.top = `${clamp(y - 6, RULER + 2, wrap.clientHeight - 30)}px`;
  ed.classList.remove('hidden');
  input.value = note.lyric || '';
  input.focus();
  input.select();
}

function commitLyricEditor(tab = false) {
  const ed = $('#lyricEditor');
  if (ed.classList.contains('hidden')) return;
  const input = $('#lyricEditorInput');
  const note = findNote(S.editingNote);
  if (note) {
    if (note.lyric !== input.value) pushUndo();
    note.lyric = input.value;
    S.lastLyric = input.value;
    S.defaultLyric = input.value || S.defaultLyric;
    $('#defaultLyric').value = S.defaultLyric;
    S.dirty = true;
    updateSelectionUI();
    requestDraw();
  }
  ed.classList.add('hidden');
  const finished = S.editingNote;
  S.editingNote = null;
  if (tab) {
    const entries = allNotes().sort((a, b) => a.note.start - b.note.start || a.note.midi - b.note.midi);
    const idx = entries.findIndex((e) => e.note.id === finished);
    const next = entries[idx + 1];
    if (next) { selectOnly(next.note, next.ti); openLyricEditor(next.note); }
  }
}

$('#lyricEditorInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); commitLyricEditor(false); }
  else if (e.key === 'Tab') { e.preventDefault(); commitLyricEditor(true); }
  else if (e.key === 'Escape') { e.preventDefault(); $('#lyricEditor').classList.add('hidden'); S.editingNote = null; }
  e.stopPropagation();
});
$('#lyricEditorInput').addEventListener('blur', () => {
  setTimeout(() => {
    if (S.editingNote && document.activeElement !== $('#lyricEditorInput')) commitLyricEditor(false);
  }, 90);
});

/* ------------------------------------------------------------------ undo */
function snapshot() {
  return JSON.stringify({ project: S.project, id: S.projectId });
}
function pushUndo() {
  S.undo.push(snapshot());
  if (S.undo.length > 100) S.undo.shift();
  S.redo = [];
  updateUndoButtons();
}
function restore(json) {
  const data = JSON.parse(json);
  S.project = data.project;
  S.projectId = data.id;
  S.selection.clear();
  S.drag = null;
  S.marquee = null;
  syncAllControls();
  renderTracks();
  renderVoiceSelect();
  renderVoices();
  updateSelectionUI();
  refreshEmptyState();
  requestDraw();
}
function undo() {
  if (!S.undo.length) return;
  S.redo.push(snapshot());
  restore(S.undo.pop());
  updateUndoButtons();
}
function redo() {
  if (!S.redo.length) return;
  S.undo.push(snapshot());
  restore(S.redo.pop());
  updateUndoButtons();
}
function updateUndoButtons() {
  $('#btnUndo').style.opacity = S.undo.length ? '1' : '.35';
}

/* ------------------------------------------------------------------ render */
async function doRender(playAfter = false) {
  if (!S.project) return;
  if (S.jobId) { toast('A render is already running'); return; }
  saveProject(true).catch(() => {});
  const options = {
    mode: $('#modeSel').value,
    voiceId: $('#voiceSelect').value || null,
    pitch: clamp(parseInt($('#pitchShift').value, 10) || 0, -24, 24),
  };
  setStatus('Preparing render…', 'busy');
  $('#btnRender').disabled = true;
  $('#btnCancel').classList.remove('hidden');
  $('#renderLog').classList.remove('hidden');
  $('#renderLog').textContent = '';
  $('#renderBar').style.width = '0%';
  $('#renderStatus').textContent = 'Starting…';
  S.playAfter = playAfter;

  try {
    const job = await api('/api/render', { method: 'POST', body: { project: S.project, options } });
    S.jobId = job.id;
    $('#renderStatus').textContent = 'Queued…';
    pollJob(job.id);
  } catch (err) {
    setStatus('Render failed', 'bad');
    $('#btnRender').disabled = false;
    $('#btnCancel').classList.add('hidden');
    toast(err.message, 'error', 7000);
  }
}

function pollJob(id) {
  clearTimeout(S.jobTimer);
  const tick = async () => {
    try {
      const job = await api(`/api/job?id=${encodeURIComponent(id)}`);
      if (job.status === 'running' || job.status === 'queued') {
        $('#renderBar').style.width = `${job.progress || 0}%`;
        $('#renderStatus').textContent = job.message || 'Rendering…';
        if (job.log && job.log.length) {
          $('#renderLog').textContent = job.log.slice(-12).join('\n');
          $('#renderLog').scrollTop = $('#renderLog').scrollHeight;
        }
        setStatus(job.message || 'Rendering…', 'busy');
        S.jobTimer = setTimeout(tick, 450);
        return;
      }
      S.jobId = null;
      $('#btnRender').disabled = false;
      $('#btnCancel').classList.add('hidden');
      if (job.status === 'done') {
        onRenderDone(job.result);
      } else if (job.status === 'cancelled') {
        setStatus('Render cancelled', 'bad');
        $('#renderStatus').textContent = 'Cancelled';
        toast('Render cancelled');
      } else {
        setStatus('Render failed', 'bad');
        $('#renderStatus').textContent = job.error || 'Render failed';
        $('#renderLog').textContent = (job.log || []).slice(-20).join('\n');
        toast(job.error || 'Render failed', 'error', 7000);
      }
    } catch (err) {
      S.jobId = null;
      $('#btnRender').disabled = false;
      $('#btnCancel').classList.add('hidden');
      setStatus('Render failed', 'bad');
      toast(err.message, 'error');
    }
  };
  tick();
}

function onRenderDone(meta) {
  S.render = meta;
  S.audioMode = 'final';
  S.audio.pause();
  S.audio.src = meta.audioUrl;
  S.audio.load();
  $('#btnExport').disabled = false;
  $('#btnCompare').disabled = !meta.rvc?.used;
  $('#renderBar').style.width = '100%';
  $('#renderStatus').textContent = `Rendered in ${meta.elapsed}s · ${meta.duration.toFixed(1)}s audio`;
  $('#renderLog').textContent = (meta.log || []).join('\n');
  const badge = $('#renderBadge');
  badge.classList.remove('hidden', 'rvc', 'dsp');
  if (meta.rvc?.used) {
    badge.classList.add('rvc');
    badge.textContent = `RVC · ${meta.rvc.voice || 'voice'}`;
  } else {
    badge.classList.add('dsp');
    badge.textContent = 'DSP singer';
  }
  $('#renderMeta').textContent = `${meta.sampleRate / 1000} kHz · ${meta.duration.toFixed(2)}s` +
    (meta.rvc?.used ? ` · ${meta.rvc.f0Method || ''}` : '') +
    (meta.rvc?.pitch ? ` · ${meta.rvc.pitch > 0 ? '+' : ''}${meta.rvc.pitch} st` : '');
  drawWave();
  setStatus('Ready', 'ok');
  if (meta.warnings?.length) toast(meta.warnings[0], '', 6000);
  else toast('Render complete', 'ok', 2200);
  S.playheadBeat = 0;

  if (S.playAfter) {
    S.playAfter = false;
    S.audio.play().catch(() => {});
  }
  requestDraw();
  setTimeout(() => { if (S.render) $('#renderLog').classList.add('hidden'); }, 1400);
}

function setStatus(text, kind = '') {
  $('#statusText').textContent = text;
  const dot = $('#statusDot');
  dot.className = 'dot' + (kind ? ` ${kind}` : '') + (kind === 'busy' ? '' : '');
}

$('#btnRender').onclick = () => doRender(false);
$('#btnCancel').onclick = async () => {
  if (!S.jobId) return;
  try { await api('/api/cancel', { method: 'POST', body: { id: S.jobId } }); } catch (e) { /* noop */ }
};
$('#btnExport').onclick = () => {
  if (!S.render) return;
  const name = S.render.audioUrl.split('/').pop();
  const a = document.createElement('a');
  a.href = `/api/download/${name}`;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
};
$('#btnCompare').onclick = () => {
  if (!S.render) return;
  const wasPlaying = !S.audio.paused;
  const t = S.audio.currentTime;
  S.audioMode = S.audioMode === 'final' ? 'source' : 'final';
  S.audio.src = S.audioMode === 'final' ? S.render.audioUrl : S.render.sourceUrl;
  S.audio.load();
  S.audio.currentTime = t;
  $('#btnCompare').textContent = S.audioMode === 'final' ? 'A/B source' : 'A/B voice';
  if (wasPlaying) S.audio.play().catch(() => {});
};

/* ------------------------------------------------------------------ transport */
$('#btnPlay').onclick = () => {
  if (!S.render) { doRender(true); return; }
  if (S.audio.paused) S.audio.play().catch(() => {});
  else S.audio.pause();
};
$('#btnStop').onclick = () => {
  S.audio.pause();
  S.audio.currentTime = 0;
  S.playheadBeat = 0;
  updateTime();
  requestDraw();
  updateTransport();
};
$('#btnRewind').onclick = () => {
  S.audio.currentTime = 0;
  S.playheadBeat = 0;
  updateTime();
  requestDraw();
};

waveCanvas.addEventListener('click', (e) => {
  if (!S.render) return;
  const rect = waveCanvas.getBoundingClientRect();
  const frac = clamp((e.clientX - rect.left) / rect.width, 0, 1);
  if (isFinite(S.audio.duration)) {
    S.audio.currentTime = frac * S.audio.duration;
    updateTime();
    requestDraw();
  }
});

/* ------------------------------------------------------------------ toolbar */
$$('.tool[data-tool]').forEach((btn) => {
  btn.onclick = () => {
    S.tool = btn.dataset.tool;
    $$('.tool[data-tool]').forEach((b) => b.classList.toggle('active', b === btn));
    canvas.style.cursor = S.tool === 'draw' ? 'copy' : S.tool === 'erase' ? 'not-allowed' : 'default';
  };
});
$('#btnZoomIn').onclick = () => { S.zoom = clamp(S.zoom * 1.2, 0.3, 4); $('#zoomLabel').textContent = `${Math.round(S.zoom * 100)}%`; requestDraw(); };
$('#btnZoomOut').onclick = () => { S.zoom = clamp(S.zoom / 1.2, 0.3, 4); $('#zoomLabel').textContent = `${Math.round(S.zoom * 100)}%`; requestDraw(); };
$('#snapSel').onchange = (e) => { S.snap = parseFloat(e.target.value); };
$('#defaultLyric').onchange = (e) => { S.defaultLyric = e.target.value || 'la'; };
$('#btnAddTrack').onclick = addTrack;
$('#btnDuplicate').onclick = duplicateSelected;
$('#btnDeleteNotes').onclick = () => removeNotes(new Set(S.selection));
$('#btnUndo').onclick = undo;
$('#btnSave').onclick = () => saveProject(false);
$('#btnDemoLoad').onclick = async () => {
  const data = await api('/api/demo');
  setProject(data.project, null);
  refreshEmptyState();
};
$('#btnRvcCheck').onclick = async () => {
  $('#rvcChip').className = 'chip busy';
  $('#rvcChip').textContent = 'checking…';
  try {
    await api('/api/rvc/check', { method: 'POST' });
    setTimeout(refreshRvc, 600);
  } catch (err) { toast(err.message, 'error'); }
};
$('#btnRvcHelp').onclick = () => openModal('Enable RVC voices', `
  <p>AsukaRVC-SVC sings with a built-in formant engine. To turn that performance into a real
  RVC voice, install the AI environment once:</p>
  <h3>1 · Install the RVC environment</h3>
  <pre>powershell -ExecutionPolicy Bypass -File tools\\setup_rvc.ps1</pre>
  <p>This creates <code>.venv-rvc</code> with PyTorch and downloads the ContentVec /
  RMVPE models (about 1 GB on CPU).</p>
  <h3>2 · Add a voicebank</h3>
  <p>Drop a RVC <code>.pth</code> model (and its <code>.index</code> if you have one) into
  <code>models\\</code>, or use the <b>Upload</b> button. Models trained with Applio,
  RVC WebUI or any RVC v1/v2 trainer work.</p>
  <h3>3 · Sing</h3>
  <p>Write lyrics on the piano roll, press <b>Render voice</b> and the engine renders a
  16 kHz source performance, converts it with your voicebank, then masters the result.</p>
  <h3>How it works</h3>
  <pre>score → phonemes → formant singer (16 kHz) → RVC → master WAV</pre>
  <p>Because the source carries the exact pitch curve from the piano roll, RVC preserves
  your melody, timing, vibrato and consonant articulation.</p>
  <h3>Shortcuts</h3>
  <p><kbd>Space</kbd> play · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> render · <kbd>N</kbd> draw ·
  <kbd>V</kbd> select · <kbd>E</kbd> erase · <kbd>Del</kbd> delete · <kbd>Ctrl</kbd>+<kbd>Z</kbd> undo ·
  <kbd>Tab</kbd> next lyric</p>
`);

/* ------------------------------------------------------------------ upload */
function openUploadModal(pthFile = null, indexFile = null) {
  const html = `
    <div class="two-col">
      <label class="field">Voice name<input id="upName" value="${pthFile ? escapeHtml(pthFile.name.replace(/\.pth$/i, '')) : ''}" placeholder="e.g. Luna"></label>
      <label class="field">Pitch shift (semitones)<input id="upPitch" type="number" value="0" step="1"></label>
    </div>
    <div class="two-col">
      <label class="field">Speaker ID<input id="upSid" type="number" value="0" min="0" step="1"></label>
      <label class="field">Color<input id="upColor" type="color" value="#d81f2a"></label>
    </div>
    <label class="field">RVC model (.pth)<input id="upPth" type="file" accept=".pth"></label>
    <label class="field">FAISS index (.index, optional)<input id="upIndex" type="file" accept=".index"></label>
    <div class="row gap" style="margin-top:14px">
      <button id="upSubmit" class="primary">Install voicebank</button>
      <span id="upStatus" class="small-text"></span>
    </div>
    <p class="small-text">Models stay on your machine in <code>models/</code>.</p>
  `;
  openModal('Add voicebank', html);
  const pthInput = $('#upPth');
  if (pthFile) {
    const dt = new DataTransfer();
    dt.items.add(pthFile);
    pthInput.files = dt.files;
    if (indexFile) {
      const di = new DataTransfer();
      di.items.add(indexFile);
      $('#upIndex').files = di.files;
    }
  }
  $('#upSubmit').onclick = async () => {
    const pth = pthInput.files[0];
    if (!pth) { $('#upStatus').textContent = 'Choose a .pth file first.'; return; }
    const fd = new FormData();
    fd.append('name', $('#upName').value || pth.name.replace(/\.pth$/i, ''));
    fd.append('pitch', $('#upPitch').value || '0');
    fd.append('sid', $('#upSid').value || '0');
    fd.append('color', $('#upColor').value || '#d81f2a');
    fd.append('pth', pth);
    const idx = $('#upIndex').files[0];
    if (idx) fd.append('index', idx);
    const btn = $('#upSubmit');
    btn.disabled = true;
    $('#upStatus').textContent = 'Uploading…';
    try {
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/voices');
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) $('#upStatus').textContent = `Uploading… ${Math.round(ev.loaded / ev.total * 100)}%`;
        };
        xhr.onload = () => {
          try {
            const data = JSON.parse(xhr.responseText);
            if (xhr.status >= 400) reject(new Error(data.error || 'Upload failed'));
            else resolve(data);
          } catch (err) { reject(err); }
        };
        xhr.onerror = () => reject(new Error('Network error during upload'));
        xhr.send(fd);
      });
      S.voices = (await api('/api/voices')).voices;
      renderVoices();
      renderVoiceSelect();
      if (S.voices.length) selectVoice(S.voices[S.voices.length - 1].id);
      closeModal();
      toast('Voicebank installed', 'ok');
    } catch (err) {
      $('#upStatus').textContent = err.message;
      btn.disabled = false;
    }
  };
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

$('#btnVoiceUpload').onclick = () => openUploadModal();
$('#filePth').onchange = (e) => { if (e.target.files[0]) openUploadModal(e.target.files[0]); e.target.value = ''; };

const drop = $('#uploadDrop');
drop.onclick = () => $('#filePth').click();
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.add('drag');
}));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.remove('drag');
}));
drop.addEventListener('drop', (e) => {
  const files = [...(e.dataTransfer?.files || [])];
  const pth = files.find((f) => f.name.toLowerCase().endsWith('.pth'));
  const index = files.find((f) => f.name.toLowerCase().endsWith('.index'));
  if (!pth) { toast('Drop a .pth voice model', 'error'); return; }
  openUploadModal(pth, index);
});

/* ------------------------------------------------------------------ projects UI */
$('#projectSelect').onchange = async (e) => {
  const v = e.target.value;
  if (v === '__demo') {
    const data = await api('/api/demo');
    setProject(data.project, null);
    S.dirty = true;
    toast('Demo song loaded — write lyrics or hit Render', 'ok', 3200);
  } else if (v === '__new') {
    const empty = {
      schema: 2, id: uid('prj'), name: 'Untitled', bpm: 120, timeSignature: [4, 4],
      key: 'C major',
      tracks: [{ id: uid('trk'), name: 'Lead', gain: 1, pan: 0, muted: false, color: TRACK_COLORS[0], notes: [] }],
      voice: JSON.parse(JSON.stringify(S.project.voice)),
      loop: { start: 0, end: 16 },
    };
    empty.voice.id = S.project.voice.id;
    setProject(empty, null);
    S.dirty = true;
    toast('New project — double-click the roll to draw notes');
  } else if (v !== '__current') {
    if (S.dirty && !confirm('Discard unsaved changes?')) { renderProjectSelect(); return; }
    await openProject(v);
  }
  renderProjectSelect();
};

$('#bpm').addEventListener('input', requestDraw);
window.addEventListener('beforeunload', (e) => {
  if (S.dirty) {
    e.preventDefault();
    e.returnValue = '';
  }
});

/* ------------------------------------------------------------------ keyboard */
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = ['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable;
  if (typing) return;

  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
    return;
  }
  if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
  if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); saveProject(false); return; }
  if (mod && e.key === 'Enter') { e.preventDefault(); doRender(false); return; }
  if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicateSelected(); return; }
  if (mod && e.key.toLowerCase() === 'c') { copySelected(); return; }
  if (mod && e.key.toLowerCase() === 'v') { pasteClipboard(); return; }

  if (e.code === 'Space') { e.preventDefault(); $('#btnPlay').click(); return; }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removeNotes(new Set(S.selection)); return; }
  if (e.key === 'Home') { e.preventDefault(); $('#btnRewind').click(); return; }
  if (e.key === 'v' || e.key === 'V') { $$('.tool[data-tool="select"]')[0].click(); return; }
  if (e.key === 'n' || e.key === 'N') { $$('.tool[data-tool="draw"]')[0].click(); return; }
  if (e.key === 'e' || e.key === 'E') { $$('.tool[data-tool="erase"]')[0].click(); return; }
  if (e.key === '+' || e.key === '=') { $('#btnZoomIn').click(); return; }
  if (e.key === '-') { $('#btnZoomOut').click(); return; }

  const step = e.shiftKey ? (S.snap || 0.25) * 4 : (S.snap || 0.25);
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault();
    const dx = e.key === 'ArrowLeft' ? -step : step;
    for (const { note } of selectedEntries()) note.start = Math.max(0, note.start + dx);
    S.dirty = true; updateSelectionUI(); requestDraw();
  }
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
    e.preventDefault();
    transposeSelected(e.key === 'ArrowUp' ? 1 : -1);
  }
});

let clipboard = [];
function copySelected() {
  clipboard = selectedEntries().map(({ note }) => ({ ...note }));
  if (clipboard.length) toast(`Copied ${clipboard.length} note${clipboard.length > 1 ? 's' : ''}`, '', 1200);
}
function pasteClipboard() {
  if (!clipboard.length) return;
  pushUndo();
  const base = Math.min(...clipboard.map((n) => n.start));
  const target = S.project.tracks[S.activeTrack];
  const ids = [];
  for (const n of clipboard) {
    const copy = { ...n, id: uid(), start: n.start - base + snapBeat(S.playheadBeat) };
    target.notes.push(copy);
    ids.push(copy.id);
  }
  S.selection = new Set(ids);
  S.dirty = true;
  updateSelectionUI();
  refreshEmptyState();
  requestDraw();
}
function duplicateSelected() {
  const entries = selectedEntries();
  if (!entries.length) return;
  pushUndo();
  const end = Math.max(...entries.map(({ note }) => note.start + note.dur));
  const offset = S.snap ? Math.ceil(end / S.snap) * S.snap : end;
  const ids = [];
  for (const { note, track } of entries) {
    const copy = { ...note, id: uid(), start: note.start + offset };
    track.notes.push(copy);
    ids.push(copy.id);
  }
  S.selection = new Set(ids);
  S.dirty = true;
  updateSelectionUI();
  requestDraw();
}

/* ------------------------------------------------------------------ resize */
const ro = new ResizeObserver(() => { requestDraw(); drawWave(); });
ro.observe(wrap);
ro.observe(waveCanvas.parentElement);

/* ------------------------------------------------------------------ boot */
readTheme();
applyTheme(themeState.id);
const themeSel = $('#themeSel');
if (themeSel) {
  themeSel.onchange = () => {
    if (themeSel.value === 'custom') openThemeModal();
    else applyTheme(themeSel.value);
  };
}
initSliders();
renderProjectSelect();
loadState();

setInterval(() => {
  const dots = $('#statusDot');
  if (!S.jobId) return;
}, 2000);
