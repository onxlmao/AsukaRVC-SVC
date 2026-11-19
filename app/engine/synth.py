"""
AsukaRVC-SVC singing engine.

Turns a note score (midi + lyric + timing) into a 16 kHz monophonic vocal that
keeps the exact melody of the score.  This signal is the "source" that RVC
converts into the chosen voicebank's timbre.

Design: parallel-formant (Klatt-style) synthesiser with a Rosenberg glottal
pulse, per-phoneme articulation, vibrato, portamento and consonant noise.
Pure Python on purpose — the app runs without numpy/torch installed.
"""

from __future__ import annotations

import math
import random

from .phonemes import (
    AFFRICATES,
    PHONES,
    SONORANT_SET,
    VOWEL_SET,
    phone_info,
    strip_stress,
)

SR = 16000
BLOCK = 64  # 4 ms control rate
TRANSITION = 0.040  # formant glide time between phonemes

# Vowel / consonant articulation gains
KIND_GAIN = {
    "vowel": 1.0,
    "diph": 1.0,
    "fric": 0.62,
    "stop": 0.85,
    "nasal": 0.72,
    "liquid": 0.85,
    "glide": 0.8,
    "silence": 0.0,
}


def midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _smoothstep(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def _attack_release(t: float, dur: float, attack: float, release: float) -> float:
    if t < 0 or t > dur:
        return 0.0
    a = t / attack if attack > 0 else 1.0
    r = (dur - t) / release if release > 0 else 1.0
    return min(1.0, max(0.0, a), max(0.0, r))


# --------------------------------------------------------------------------- #
# Glottal source
# --------------------------------------------------------------------------- #
def _glottal_table(size: int = 4096):
    t_open, t_close = 0.42, 0.20
    table = []
    for i in range(size):
        t = i / size
        if t < t_open:
            v = 0.5 * (1.0 - math.cos(math.pi * t / t_open))
        elif t < t_open + t_close:
            v = math.cos(math.pi * (t - t_open) / (2.0 * t_close))
        else:
            v = 0.0
        table.append(v)
    # Differentiate the flow to obtain the glottal flow derivative.
    out = [table[(i + 1) % size] - table[i] for i in range(size)]
    mean = sum(out) / size
    out = [v - mean for v in out]
    rms = math.sqrt(sum(v * v for v in out) / size) or 1.0
    return [v / rms * 0.22 for v in out]


GLOTTAL = _glottal_table()


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def _expand_phones(phones):
    out = []
    for p in phones:
        base = strip_stress(p)
        if base in AFFRICATES:
            out.extend(AFFRICATES[base])
        elif base in PHONES:
            out.append(p)
    return out


def phoneme_schedule(lyric: str, note_dur: float, g2p, *, short: bool = False):
    """Return [(phone, start_offset, duration, stress)] for one note."""
    phones = _expand_phones(g2p.word_to_phones(lyric)) if lyric else []
    if not phones:
        phones = ["AH0"]
    onset, nucleus, coda = g2p.split_syllable(phones)
    if not nucleus:
        nucleus = [phones[0]]
        onset, coda = [], phones[1:]

    def nominal(p):
        info = phone_info(p)
        d = info["dur"]
        if info["kind"] == "vowel":
            return 0.09
        if info["kind"] == "diph":
            return 0.12
        return d

    # consonant budgets
    onset_total = sum(nominal(p) for p in onset)
    coda_total = sum(nominal(p) for p in coda)
    max_cons = max(0.0, note_dur * 0.55)
    if onset_total + coda_total > max_cons:
        scale = max_cons / (onset_total + coda_total) if (onset_total + coda_total) else 0.0
        onset_total *= scale
        coda_total *= scale
    vowel_dur = max(0.045, note_dur - onset_total - coda_total)
    if short and note_dur < 0.16:
        vowel_dur = max(0.03, vowel_dur)

    schedule = []
    t = 0.0
    for p in onset:
        d = nominal(p) * (onset_total / max(1e-6, sum(nominal(q) for q in onset)))
        d = min(d, max(0.02, onset_total))
        schedule.append((p, t, d))
        t += d
    # the last onset consonant gets a small hand-off into the vowel
    n = len(nucleus)
    for i, p in enumerate(nucleus):
        d = vowel_dur / n
        schedule.append((p, t, d))
        t += d
    for p in coda:
        d = nominal(p) * (coda_total / max(1e-6, sum(nominal(q) for q in coda)))
        d = min(d, max(0.02, coda_total))
        schedule.append((p, t, d))
        t += d

    # normalise to the note length
    total = sum(s[2] for s in schedule) or note_dur
    if abs(total - note_dur) > 1e-4:
        k = note_dur / total
        schedule = [(p, st * k, d * k) for p, st, d in schedule]
    return schedule


class NotePlan:
    __slots__ = (
        "midi", "start", "end", "lyric", "velocity", "segments", "vib_phase",
        "vib_rate", "drift_phase", "prev_end_midi", "glide",
    )

    def __init__(self):
        self.segments = []


def build_plan(notes, bpm: float, g2p, voice: dict):
    spb = 60.0 / bpm
    valid = []
    for n in notes:
        try:
            dur = float(n.get("dur", 1.0))
            start = float(n.get("start", 0.0))
        except (TypeError, ValueError):
            continue
        if dur <= 0.01:
            continue
        valid.append((start, dur, n))
    valid.sort(key=lambda x: x[0])

    plans = []
    prev_end = -10.0
    prev_midi = None
    rng = random.Random(1337)
    for idx, (start, dur, n) in enumerate(valid):
        plan = NotePlan()
        plan.start = start * spb
        plan.end = plan.start + dur * spb
        try:
            plan.midi = float(n.get("midi", 60))
        except (TypeError, ValueError):
            plan.midi = 60.0
        plan.lyric = str(n.get("lyric", "la") or "la")
        try:
            plan.velocity = max(0.05, min(1.0, float(n.get("velocity", 0.82))))
        except (TypeError, ValueError):
            plan.velocity = 0.82

        short_note = dur * spb < 0.18
        schedule = phoneme_schedule(plan.lyric, plan.end - plan.start, g2p, short=short_note)
        for phone, off, d in schedule:
            plan.segments.append((phone, plan.start + off, plan.start + off + d))

        plan.vib_rate = float(voice.get("vibratoRate", 5.6)) + rng.uniform(-0.15, 0.15)
        plan.vib_phase = rng.uniform(0.0, 2.0 * math.pi)
        plan.drift_phase = rng.uniform(0.0, 6.28)
        gap = plan.start - prev_end
        plan.glide = plan.midi - prev_midi if (prev_midi is not None and gap < 0.14) else None
        plan.prev_end_midi = prev_midi
        prev_end = plan.end
        prev_midi = plan.midi
        plans.append(plan)
    return plans


# --------------------------------------------------------------------------- #
# Synthesiser
# --------------------------------------------------------------------------- #
class Singer:
    def __init__(self, g2p, sample_rate: int = SR):
        self.g2p = g2p
        self.sr = sample_rate
        self.glottal = GLOTTAL

    def render(self, notes, bpm: float, voice: dict, progress=None, start_beat=0.0):
        sr = self.sr
        plans = build_plan(notes, bpm, self.g2p, voice)
        if not plans:
            return [0.0] * int(0.5 * sr), []

        spb = 60.0 / bpm
        total = (max(p.end for p in plans) - start_beat * spb) * 1.0 + float(voice.get("tail", 0.9))
        total = max(0.4, total)
        n_samples = int(total * sr)
        out = [0.0] * n_samples

        # Segment table for fast lookup
        segs = []
        for plan in plans:
            for phone, s0, s1 in plan.segments:
                if s1 <= s0:
                    continue
                segs.append((s0, s1, phone, plan))
        segs.sort(key=lambda x: x[0])

        vibrato_depth = float(voice.get("vibratoDepth", 0.20))  # semitones
        vibrato_delay = float(voice.get("vibratoDelay", 0.16))
        vibrato_ramp = float(voice.get("vibratoRamp", 0.28))
        scoop = float(voice.get("scoop", 0.12))  # semitones
        breath = max(0.0, min(1.0, float(voice.get("breathiness", 0.12))))
        brightness = max(0.05, min(1.0, float(voice.get("brightness", 0.55))))
        jitter = float(voice.get("jitter", 0.006))
        dyn = float(voice.get("dynamics", 0.5))

        # per-voice resonance scaling (formant shift)
        fscale = float(voice.get("formantShift", 1.0))
        fscale = max(0.75, min(1.35, fscale))

        rng = random.Random(42)
        seg_i = 0
        n_segs = len(segs)

        # glottal phase and filter states
        phase = 0.0
        tilt = 0.0
        # 3 formant biquads (parallel)
        b0 = [0.0, 0.0, 0.0]
        b2 = [0.0, 0.0, 0.0]
        a1 = [0.0, 0.0, 0.0]
        a2 = [0.0, 0.0, 0.0]
        z1 = [0.0, 0.0, 0.0]
        z2 = [0.0, 0.0, 0.0]
        # noise bandpass
        nb0 = nb2 = na1 = na2 = 0.0
        nz1 = nz2 = 0.0
        # breath bandpass
        bb0 = bb2 = ba1 = ba2 = 0.0
        bz1 = bz2 = 0.0
        # highpass state (DC / rumble)
        hp_x1 = hp_y1 = 0.0
        hp_a = math.exp(-2.0 * math.pi * 70.0 / sr)

        tilt_coeff = 0.06 + brightness * 0.55

        last_control = None
        cur = dict(f=[500.0, 1500.0, 2500.0], bw=[100.0, 140.0, 180.0],
                   voiced=0.0, noise=0.0, nf=2500.0, nbw=1500.0,
                   voiced_gain=0.0, noise_gain=0.0, breath_gain=0.0)
        controls = dict(cur)

        block = 0
        progress_step = max(1, int(0.25 * sr / BLOCK))
        for sample_start in range(0, n_samples, BLOCK):
            n_block = min(BLOCK, n_samples - sample_start)
            t = (sample_start + n_block * 0.5) / sr

            # ---- locate phone ------------------------------------------------
            while seg_i < n_segs and segs[seg_i][1] <= t:
                seg_i += 1
            if seg_i < n_segs and segs[seg_i][0] <= t < segs[seg_i][1]:
                s0, s1, phone, plan = segs[seg_i]
                info = phone_info(phone)
                local = (t - s0) / max(1e-5, s1 - s0)
                f = list(info["f"])
                # diphthong: glide to the target
                if info["kind"] == "diph" and info["target"]:
                    k = _smoothstep(local)
                    f = [f[i] + (info["target"][i] - f[i]) * k for i in range(3)]
                # formant glide from previous phone
                prev_info = None
                if seg_i > 0:
                    prev_info = phone_info(segs[seg_i - 1][2])
                if prev_info and t - s0 < TRANSITION:
                    k = _smoothstep((t - s0) / TRANSITION)
                    f = [prev_info["f"][i] + (f[i] - prev_info["f"][i]) * k for i in range(3)]
                # formant glide into next phone
                next_info = None
                if seg_i + 1 < n_segs:
                    next_info = phone_info(segs[seg_i + 1][2])
                if next_info and s1 - t < TRANSITION:
                    k = _smoothstep((s1 - t) / TRANSITION)
                    f = [next_info["f"][i] + (f[i] - next_info["f"][i]) * k for i in range(3)]

                kind = info["kind"]
                amp = KIND_GAIN.get(kind, 0.8)
                if kind == "nasal":
                    amp *= 0.95
                # phone envelope
                env = _attack_release(
                    t - s0, s1 - s0,
                    attack=0.022 if kind in ("vowel", "diph") else 0.012,
                    release=0.018 if kind in ("vowel", "diph") else 0.014,
                )
                if kind == "stop":
                    # closure -> burst -> aspiration
                    frac = local
                    if frac < 0.42:
                        env *= 0.05
                    elif frac < 0.55:
                        env *= (frac - 0.42) / 0.13
                    else:
                        env *= math.exp(-(frac - 0.55) * 5.0)
                    amp *= 1.1
                note_env = self._note_env(t, plan, dyn)
                vel = plan.velocity
                voiced_amp = info["voiced"] * env * amp * note_env * vel
                if kind in ("fric", "stop"):
                    voiced_amp *= 0.35
                noise_amp = info["noise"] * env * note_env * vel
                if kind == "fric":
                    noise_amp *= 0.9
                controls = dict(
                    f=f, bw=info["bw"],
                    voiced=info["voiced"],
                    noise=noise_amp,
                    nf=info["noise_f"],
                    nbw=info["noise_bw"],
                    voiced_gain=voiced_amp,
                    noise_gain=noise_amp,
                    breath_gain=breath * 0.55 * note_env * (0.35 + 0.65 * info["voiced"]),
                )
                controls["plan"] = plan
                controls["phone"] = phone
            else:
                # silence between phrases: keep the last formants, fade out
                controls = dict(controls)
                for key in ("voiced_gain", "noise_gain", "breath_gain"):
                    controls[key] *= 0.985
                controls["plan"] = None
                controls["phone"] = None

            # ---- F0 ----------------------------------------------------------
            plan = controls.get("plan")
            if plan is not None:
                f0 = self._f0(t, plan, vibrato_depth, vibrato_delay, vibrato_ramp,
                              scoop, jitter, rng)
                f0 *= 2.0 ** (float(voice.get("transpose", 0.0)) / 12.0)
            else:
                f0 = 0.0

            # ---- update filter coefficients ---------------------------------
            gain3 = self._formant_gains(controls.get("phone"))
            for i in range(3):
                fc = max(80.0, min(sr * 0.45, controls["f"][i] * fscale))
                bw = max(50.0, controls["bw"][i])
                q = fc / bw
                w0 = 2.0 * math.pi * fc / sr
                alpha = math.sin(w0) / (2.0 * q)
                a0 = 1.0 + alpha
                b0[i] = alpha / a0
                b2[i] = -alpha / a0
                a1[i] = (-2.0 * math.cos(w0)) / a0
                a2[i] = (1.0 - alpha) / a0

            nf = max(150.0, min(sr * 0.47, controls["nf"]))
            nbw = max(150.0, controls["nbw"])
            q = nf / nbw
            w0 = 2.0 * math.pi * nf / sr
            alpha = math.sin(w0) / (2.0 * q)
            a0 = 1.0 + alpha
            nb0 = alpha / a0
            nb2 = -alpha / a0
            na1 = (-2.0 * math.cos(w0)) / a0
            na2 = (1.0 - alpha) / a0

            bwc = 2400.0
            qb = 1.1
            w0 = 2.0 * math.pi * bwc / sr
            alpha = math.sin(w0) / (2.0 * qb)
            a0 = 1.0 + alpha
            bb0 = alpha / a0
            bb2 = -alpha / a0
            ba1 = (-2.0 * math.cos(w0)) / a0
            ba2 = (1.0 - alpha) / a0

            vgain = controls["voiced_gain"]
            ngain = controls["noise_gain"]
            bgain = controls["breath_gain"]
            g1, g2, g3 = gain3

            # ---- sample loop -------------------------------------------------
            for _ in range(n_block):
                x_voice = 0.0
                if vgain > 1e-5 and f0 > 20.0:
                    phase += f0 / sr
                    if phase >= 1.0:
                        phase -= 1.0
                    idx = int(phase * 4096)
                    frac = phase * 4096 - idx
                    s0v = self.glottal[idx & 4095]
                    s1v = self.glottal[(idx + 1) & 4095]
                    src = s0v + (s1v - s0v) * frac
                else:
                    src = 0.0
                    if phase:
                        phase = 0.0

                # glottal spectral tilt
                tilt += tilt_coeff * (src - tilt)
                x_voice = tilt * (0.6 + 0.8 * brightness)

                # parallel formant bank
                y1 = b0[0] * x_voice + b2[0] * z2[0] - a1[0] * z1[0] - a2[0] * z2[0]
                z2[0] = z1[0]
                z1[0] = y1
                y2 = b0[1] * x_voice + b2[1] * z2[1] - a1[1] * z1[1] - a2[1] * z2[1]
                z2[1] = z1[1]
                z1[1] = y2
                y3 = b0[2] * x_voice + b2[2] * z2[2] - a1[2] * z1[2] - a2[2] * z2[2]
                z2[2] = z1[2]
                z1[2] = y3

                voiced = (y1 * g1 + y2 * g2 + y3 * g3) * vgain * 1.9

                noise_sig = 0.0
                if ngain > 1e-5:
                    nz = rng.uniform(-1.0, 1.0)
                    ny = nb0 * nz + nb2 * nz2 - na1 * nz1 - na2 * nz2
                    nz2 = nz1
                    nz1 = nz
                    noise_sig += ny * ngain * 2.1
                if bgain > 1e-5:
                    nz = rng.uniform(-1.0, 1.0)
                    by = bb0 * nz + bb2 * bz2 - ba1 * bz1 - ba2 * bz2
                    bz2 = bz1
                    bz1 = nz
                    noise_sig += by * bgain * 1.4

                s = voiced + noise_sig
                # rumble filter
                hp_y = hp_a * (hp_y1 + s - hp_x1)
                hp_x1 = s
                hp_y1 = hp_y
                out[sample_start + _] = hp_y

            block += 1
            if progress and block % progress_step == 0:
                progress(min(0.99, sample_start / n_samples))

        # remove NaNs / clip
        for i, v in enumerate(out):
            if v != v:
                out[i] = 0.0
            elif v > 0.98:
                out[i] = 0.98
            elif v < -0.98:
                out[i] = -0.98
        if progress:
            progress(1.0)
        return out, plans

    # ------------------------------------------------------------------ #
    def _formant_gains(self, phone):
        if phone is None:
            return (1.0, 0.5, 0.25)
        info = phone_info(phone)
        kind = info["kind"]
        if kind in ("vowel", "diph"):
            return (1.0, 0.62, 0.32)
        if kind == "nasal":
            return (1.0, 0.18, 0.10)
        if kind in ("liquid", "glide"):
            return (0.9, 0.5, 0.25)
        return (0.75, 0.55, 0.35)

    @staticmethod
    def _note_env(t, plan, dynamics):
        if t < plan.start or t > plan.end:
            return 0.0
        dur = plan.end - plan.start
        attack = min(0.035, dur * 0.15)
        release = min(0.06, dur * 0.25)
        env = _attack_release(t - plan.start, dur, attack, release)
        # gentle arch for longer notes
        if dur > 0.35:
            k = (t - plan.start) / dur
            env *= 1.0 + dynamics * 0.10 * math.sin(math.pi * k)
        return env

    @staticmethod
    def _f0(t, plan, depth, delay, ramp, scoop, jitter, rng):
        base = midi_to_hz(plan.midi)
        local = t - plan.start
        dur = max(1e-4, plan.end - plan.start)
        cents = 0.0

        # portamento into the note
        if plan.glide is not None:
            g_dur = min(0.085, dur * 0.5)
            k = _smoothstep(local / g_dur)
            cents += -plan.glide * 100.0 * (1.0 - k)
        elif local < 0.06 and scoop > 0:
            k = _smoothstep(local / 0.06)
            cents += -scoop * 100.0 * (1.0 - k)

        # vibrato with delayed onset
        if depth > 0 and local > delay:
            k = min(1.0, (local - delay) / max(1e-4, ramp))
            k = _smoothstep(k)
            # vibrato grows a little on longer notes
            grow = min(1.0, 0.55 + dur * 0.45)
            cents += (
                math.sin(2.0 * math.pi * plan.vib_rate * local + plan.vib_phase)
                * depth * 100.0 * k * grow
            )

        # slow expressive drift + tiny jitter
        cents += math.sin(0.47 * local + plan.drift_phase) * 4.5
        cents += rng.uniform(-1.0, 1.0) * jitter * 100.0

        return base * (2.0 ** (cents / 1200.0))


def note_phoneme_map(notes, bpm, g2p):
    """Used by /api/g2p for the phoneme inspector."""
    out = []
    for plan in build_plan(notes, bpm, g2p, {}):
        out.append(
            {
                "lyric": plan.lyric,
                "start": round(plan.start, 3),
                "end": round(plan.end, 3),
                "midi": plan.midi,
                "phones": [
                    {
                        "phone": p,
                        "start": round(s0, 3),
                        "end": round(s1, 3),
                    }
                    for p, s0, s1 in plan.segments
                ],
            }
        )
    return out
