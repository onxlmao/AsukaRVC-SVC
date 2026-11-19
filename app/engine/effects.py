"""Mastering / audio IO helpers — stdlib only, works at any sample rate."""

from __future__ import annotations

import array
import math
import os
import wave


# --------------------------------------------------------------------------- #
# WAV IO
# --------------------------------------------------------------------------- #
def write_wav(path: str, samples, sample_rate: int, stereo: bool = False) -> str:
    """Write float samples in [-1, 1] as 16-bit PCM WAV."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = array.array("h")
    peak = 1.0
    if stereo:
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            frames.append(v)
            frames.append(v)
    else:
        for s in samples:
            if s > peak:
                peak = s
            elif s < -peak:
                peak = -s
            frames.append(int(max(-1.0, min(1.0, s)) * 32767))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2 if stereo else 1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(frames.tobytes())
    return path


def write_wav_stereo(path: str, left, right, sample_rate: int) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    frames = array.array("h")
    for l, r in zip(left, right):
        frames.append(int(max(-1.0, min(1.0, l)) * 32767))
        frames.append(int(max(-1.0, min(1.0, r)) * 32767))
    with wave.open(path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(frames.tobytes())
    return path


def read_wav(path: str):
    """Return (samples as float list in [-1,1], sample_rate, channels)."""
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        data = array.array("h")
        data.frombytes(raw)
        scale = 1.0 / 32768.0
    elif width == 1:
        data = array.array("B")
        data.frombytes(raw)
        scale = 1.0 / 128.0
    elif width == 3:
        out = []
        for i in range(0, len(raw), 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            out.append(v / 8388608.0)
        return _deinterleave(out, channels), rate, channels
    elif width == 4:
        data = array.array("i")
        data.frombytes(raw)
        scale = 1.0 / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width}")

    if channels == 1:
        samples = [v * scale for v in data]
    else:
        mono = []
        for i in range(0, len(data), channels):
            chunk = data[i : i + channels]
            mono.append(sum(chunk) / len(chunk) * scale)
        samples = mono
    return samples, rate, channels


def _deinterleave(values, channels):
    if channels == 1:
        return values
    out = []
    for i in range(0, len(values), channels):
        out.append(sum(values[i : i + channels]) / channels)
    return out


# --------------------------------------------------------------------------- #
# Basic DSP
# --------------------------------------------------------------------------- #
def peak(samples) -> float:
    p = 0.0
    for s in samples:
        a = s if s >= 0 else -s
        if a > p:
            p = a
    return p


def normalize(samples, target: float = 0.95):
    p = peak(samples)
    if p < 1e-9:
        return samples
    g = target / p
    return [s * g for s in samples]


def highpass(samples, sr: int, freq: float = 45.0):
    """RBJ biquad high pass."""
    w0 = 2.0 * math.pi * freq / sr
    cosw = math.cos(w0)
    alpha = math.sin(w0) / (2.0 * 0.707)
    a0 = 1.0 + alpha
    b0 = (1.0 + cosw) / 2.0 / a0
    b1 = -(1.0 + cosw) / a0
    b2 = b0
    a1 = -2.0 * cosw / a0
    a2 = (1.0 - alpha) / a0
    out = [0.0] * len(samples)
    x1 = x2 = y1 = y2 = 0.0
    for i, x in enumerate(samples):
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1 = x1, x
        y2, y1 = y1, y
        out[i] = y
    return out


def compressor(samples, sr: int, threshold_db: float = -20.0, ratio: float = 3.0,
               attack_ms: float = 8.0, release_ms: float = 160.0, makeup_db: float = 2.5):
    thresh = 10.0 ** (threshold_db / 20.0)
    makeup = 10.0 ** (makeup_db / 20.0)
    a_att = math.exp(-1.0 / (sr * attack_ms / 1000.0))
    a_rel = math.exp(-1.0 / (sr * release_ms / 1000.0))
    env = 0.0
    out = [0.0] * len(samples)
    for i, x in enumerate(samples):
        level = x if x >= 0 else -x
        coeff = a_att if level > env else a_rel
        env = coeff * env + (1.0 - coeff) * level
        if env > thresh and env > 1e-9:
            over = 20.0 * math.log10(env / thresh)
            gain_db = -(over - over / ratio)
            g = 10.0 ** (gain_db / 20.0)
        else:
            g = 1.0
        out[i] = x * g * makeup
    return out


def _comb(buf, input_samples, delay: int, feedback: float, damping: float):
    out = [0.0] * len(input_samples)
    store = 0.0
    n = len(buf)
    idx = 0
    for i, x in enumerate(input_samples):
        y = buf[idx]
        store = y * (1.0 - damping) + store * damping
        buf[idx] = x + store * feedback
        idx += 1
        if idx >= n:
            idx = 0
        out[i] = y
    return out


def _allpass(buf, input_samples, feedback: float = 0.5):
    out = [0.0] * len(input_samples)
    n = len(buf)
    idx = 0
    for i, x in enumerate(input_samples):
        bufout = buf[idx]
        y = -x + bufout
        buf[idx] = x + bufout * feedback
        idx += 1
        if idx >= n:
            idx = 0
        out[i] = y
    return out


def reverb(samples, sr: int, mix: float = 0.15, room: float = 0.78):
    """Schroeder reverb, scaled to the supplied sample rate."""
    if mix <= 0.0005:
        return samples
    delays = [0.0297, 0.0371, 0.0411, 0.0437]
    combs = [_comb([0.0] * int(sr * d), samples, int(sr * d), room, 0.28) for d in delays]
    wet = [0.0] * len(samples)
    for i in range(len(samples)):
        wet[i] = (combs[0][i] + combs[1][i] + combs[2][i] + combs[3][i]) * 0.25
    for d in (0.0050, 0.0017):
        wet = _allpass([0.0] * max(1, int(sr * d)), wet, 0.6)
    dry = 1.0 - mix * 0.5
    return [samples[i] * dry + wet[i] * mix for i in range(len(samples))]


def soft_limit(samples, ceiling: float = 0.97):
    out = [0.0] * len(samples)
    for i, x in enumerate(samples):
        # smooth saturation only near the ceiling
        if x > ceiling:
            out[i] = ceiling + (1.0 - ceiling) * math.tanh((x - ceiling) / (1.0 - ceiling))
        elif x < -ceiling:
            out[i] = -(ceiling + (1.0 - ceiling) * math.tanh((-x - ceiling) / (1.0 - ceiling)))
        else:
            out[i] = x
    return out


def resample(samples, sr_from: int, sr_to: int):
    if sr_from == sr_to or not samples:
        return samples
    ratio = sr_to / sr_from
    n_out = int(len(samples) * ratio)
    # simple anti-alias pre-filter when decimating
    src = samples
    if ratio < 1.0:
        cutoff = sr_to * 0.45
        src = _one_pole_lowpass(samples, sr_from, cutoff)
    out = [0.0] * n_out
    last = len(src) - 1
    for i in range(n_out):
        pos = i / ratio
        j = int(pos)
        if j >= last:
            out[i] = src[last]
        else:
            f = pos - j
            out[i] = src[j] * (1.0 - f) + src[j + 1] * f
    return out


def _one_pole_lowpass(samples, sr: int, cutoff: float):
    dt = 1.0 / sr
    rc = 1.0 / (2.0 * math.pi * cutoff)
    a = dt / (rc + dt)
    out = [0.0] * len(samples)
    y = 0.0
    for i, x in enumerate(samples):
        y += a * (x - y)
        out[i] = y
    return out


def master(samples, sr: int, *, do_compress: bool = True, reverb_mix: float = 0.12,
           gain: float = 0.9, normalize_out: bool = True):
    """Full master bus: HPF -> compressor -> reverb -> limiter -> normalize."""
    out = highpass(samples, sr, 42.0)
    if do_compress:
        out = compressor(out, sr)
    out = reverb(out, sr, reverb_mix)
    out = normalize(out, 0.98) if normalize_out else out
    out = soft_limit(out, 0.97)
    if gain != 1.0:
        out = [s * gain for s in out]
    return out


def waveform_peaks(samples, buckets: int = 600):
    """Downsample to min/max pairs for UI drawing."""
    if not samples:
        return []
    n = len(samples)
    step = max(1, n // buckets)
    peaks = []
    for start in range(0, n, step):
        chunk = samples[start : start + step]
        if not chunk:
            break
        lo = min(chunk)
        hi = max(chunk)
        peaks.append([round(lo, 4), round(hi, 4)])
    return peaks
