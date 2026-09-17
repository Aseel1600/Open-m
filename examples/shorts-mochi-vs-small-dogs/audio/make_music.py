#!/usr/bin/env python3
"""
Mochi vs Small Dogs - Shorts soundtrack generator.

Builds a 30 s punchy "hype + comedy" bed in C minor at 120 BPM with SFX:
kick / clap / hats / sub+mids bass / plucked hook / pad / risers / whooshes / booms.
Pure numpy synthesis (no samples, no API keys) -> audio/music.wav
stereo 44.1 kHz 16-bit, deterministic (fixed RNG seeds).

Run from anywhere:
    python3 audio/make_music.py
"""
import os
import wave

import numpy as np

SR = 44100
DUR = 30.0
N = int(round(SR * DUR))
BPM = 120.0
BEAT = 60.0 / BPM          # 0.5 s
BAR = 4 * BEAT             # 2.0 s
rng = np.random.default_rng(7)

music = np.zeros((N, 2), dtype=np.float64)
rng_ir = np.random.default_rng(99)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music.wav")


# ----------------------------------------------------------------- helpers
def pan_gains(pan):
    """pan in [-1, 1] -> (left, right) constant-power gains."""
    a = (pan + 1.0) * np.pi / 4.0
    return np.cos(a), np.sin(a)


def add(sig, at, gain=1.0, pan=0.0):
    """Mix a mono signal into the stereo master at time `at` (seconds)."""
    i0 = int(round(at * SR))
    if i0 >= N:
        return
    n = min(len(sig), N - i0)
    if n <= 0:
        return
    gl, gr = pan_gains(pan)
    music[i0:i0 + n, 0] += sig[:n] * gain * gl
    music[i0:i0 + n, 1] += sig[:n] * gain * gr


def lp(x, w):
    """Cheap moving-average low-pass (w = window in samples)."""
    if w < 2:
        return x
    k = np.ones(w) / w
    return np.convolve(x, k, mode="same")


def hp(x, w):
    """Cheap moving-average high-pass."""
    return x - lp(x, w)


def norm(x):
    m = np.max(np.abs(x))
    return x / m if m > 1e-9 else x


def midi(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


# ----------------------------------------------------------------- drums
def kick():
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    f = 43.0 + 115.0 * np.exp(-t / 0.024)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.135)
    click = rng.normal(0, 1, n) * np.exp(-t / 0.0045) * 0.45
    return norm(np.tanh((body + click) * 1.5)) * np.exp(-t / 0.40) / np.exp(-t / 0.40)


def clap():
    n = int(SR * 0.32)
    t = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    bright = hp(noise, 18)
    env = np.exp(-t / 0.055)
    for d in (0.0, 0.0085, 0.017):
        i = int(d * SR)
        env[i:] = np.maximum(env[:n - i], 0.55 * np.exp(-t[:n - i] / 0.02))
    body = lp(noise, 6) * np.exp(-t / 0.09) * 0.35
    return norm(bright * env * 0.95 + body)


def hat(open_=False):
    dur = 0.13 if open_ else 0.045
    n = int(SR * dur)
    t = np.arange(n) / SR
    noise = hp(hp(rng.normal(0, 1, n), 6), 3)
    env = np.exp(-t / (0.055 if open_ else 0.016))
    return norm(noise * env) * 0.55


# ----------------------------------------------------------------- bass / melodic
def bass(f, dur, drive=1.6):
    n = int(SR * dur)
    t = np.arange(n) / SR
    saw = 2.0 * ((f * t) % 1.0) - 1.0
    sq = np.sign(np.sin(2 * np.pi * f * t))
    s = lp(saw * 0.65 + sq * 0.35, 14)
    env = (1 - np.exp(-t / 0.004)) * np.exp(-t / (dur * 0.55))
    return np.tanh(s * drive) * env


def pluck(f, dur, detune=1.004):
    n = int(SR * dur)
    t = np.arange(n) / SR
    a = 2.0 * ((f * t) % 1.0) - 1.0
    b = 2.0 * ((f * detune * t) % 1.0) - 1.0
    s = (a + b) * 0.5
    s = s - 0.35 * lp(s, 7)
    env = (1 - np.exp(-t / 0.0015)) * np.exp(-t / (dur * 0.42))
    return norm(s) * env


def pad(notes, dur):
    n = int(SR * dur)
    t = np.arange(n) / SR
    s = np.zeros(n)
    for k, m in enumerate(notes):
        f = midi(m)
        for det in (-0.006, 0.005, 0.011):
            s += 2.0 * ((f * (1 + det) * t) % 1.0) - 1.0
    s = lp(s / (len(notes) * 3), 60)
    env = (1 - np.exp(-t / 0.35)) * np.minimum(1.0, np.exp(-(t - dur * 0.82) / 0.25))
    return norm(s) * env


def boom(freq=52.0, dur=1.6, bright=1.0):
    """Cinematic impact with a short fft-convolved tail."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.5)
    body += 0.5 * np.sin(2 * np.pi * freq * 2.0 * t) * np.exp(-t / 0.22)
    nz = rng.normal(0, 1, n) * np.exp(-t / 0.09)
    s = norm(body) * 0.9 + norm(lp(nz, 25)) * 0.5 * bright
    # tail via FFT convolution with a decaying noise impulse response
    m = int(SR * 0.9)
    ir = rng_ir.normal(0, 1, m) * np.exp(-np.arange(m) / (0.22 * SR))
    ir = lp(ir, 40)
    L = 1 << int(np.ceil(np.log2(n + m)))
    tail = np.fft.irfft(np.fft.rfft(s, L) * np.fft.rfft(ir, L), L)[:n]
    s = s + norm(tail) * 0.35
    return norm(s) * np.exp(-t / (dur * 0.85))


def whoosh(dur=0.75):
    n = int(SR * dur)
    t = np.arange(n) / SR
    k = t / dur
    sweep = np.sin(2 * np.pi * (180 + 2600 * k ** 2) * t)
    nz = hp(rng.normal(0, 1, n), 22)
    env = np.sin(np.pi * k) ** 1.4
    return norm(nz * 0.55 + sweep * 0.7 * hp(np.exp(-((k - 0.75) ** 2) / 0.02), 4)) * env


def riser(dur=1.6):
    n = int(SR * dur)
    t = np.arange(n) / SR
    k = t / dur
    nz = hp(rng.normal(0, 1, n), int(max(3, 30 * (1 - k).mean())))
    sweep = np.sin(2 * np.pi * (300 * 2 ** (3.2 * k)) * t)
    env = k ** 1.6
    return norm(nz * 0.5 + sweep * 0.6) * env


def blip(f=880.0, dur=0.09):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = f * np.exp(-t / 0.05)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.03)


# ----------------------------------------------------------------- arrangement
KICK, CLAP, HATC, HATO = kick(), clap(), hat(False), hat(True)

# i - VI - III - VII in C minor, resolving home at the end
BAR_ROOTS = {0: 36, 1: 32, 2: 39, 3: 34, 4: 29}
BAR_SHIFT = {0: 0, 1: -4, 2: 3, 3: -2, 4: 5}
BAR_PAD = {
    0: [60, 63, 67], 1: [60, 63, 68], 2: [63, 67, 70],
    3: [62, 65, 69], 4: [60, 65, 69],
}
BAR_ORDER = [0, 1, 2, 3] * 3 + [4, 1, 0]        # last 3 bars: Fm, Ab, Cm(hold)

# 2-bar hook melody (C minor): (beat, midi, dur_beats)
MOTIF = [
    (0.00, 67, 0.5), (0.50, 72, 0.5), (1.00, 75, 0.5), (1.50, 74, 0.25),
    (1.75, 72, 0.25), (2.00, 67, 1.0), (3.00, 70, 0.5), (3.50, 72, 0.5),
    (4.00, 68, 0.5), (4.50, 72, 0.5), (5.00, 75, 0.5), (5.50, 77, 0.5),
    (6.00, 75, 1.0), (7.00, 72, 0.5), (7.50, 70, 0.5),
]

SECTION = {}
for b in range(15):
    t0 = b * BAR
    if t0 < 3.9:
        SECTION[b] = "intro"
    elif t0 < 15.9:
        SECTION[b] = "main"
    elif t0 < 23.9:
        SECTION[b] = "big"
    else:
        SECTION[b] = "outro"

for b in range(15):
    t0 = b * BAR
    sec = SECTION[b]
    order_idx = BAR_ORDER[b] if b < len(BAR_ORDER) else 0
    root = BAR_ROOTS[order_idx]

    # ---- pad
    pad_gain = {"intro": 0.30, "main": 0.26, "big": 0.32, "outro": 0.34}[sec]
    pad_dur = BAR if sec != "outro" else 2 * BAR
    add(pad(BAR_PAD[order_idx], pad_dur), t0, gain=pad_gain, pan=-0.25)
    if sec in ("big", "outro"):
        add(pad(BAR_PAD[order_idx], pad_dur), t0, gain=pad_gain * 0.7, pan=0.35)

    # ---- drums
    if sec == "intro":
        if b == 0:
            add(HATC, t0 + BEAT * 0.0, 0.30, pan=0.2)
            add(HATC, t0 + BEAT * 1.0, 0.26, pan=-0.2)
            add(HATC, t0 + BEAT * 2.0, 0.30, pan=0.2)
            add(KICK, t0, 0.85)
            add(HATC, t0 + BEAT * 3.0, 0.26, pan=-0.2)
            add(CLAP, t0 + BEAT * 3.0, 0.35)
        else:
            for i in range(8):                      # 8th-note hats
                add(HATC, t0 + i * BEAT / 2, 0.16 if i % 2 else 0.26,
                    pan=0.22 if i % 2 else -0.22)
            add(KICK, t0, 0.9)
            add(KICK, t0 + BEAT * 2.5, 0.8)
            add(CLAP, t0 + BEAT * 2, 0.5)
            add(CLAP, t0 + BEAT * 3.5, 0.25)
    elif sec in ("main", "big"):
        heavy = sec == "big"
        for i in range(8):
            openn = (i == 7)
            add(HATO if openn else HATC, t0 + i * BEAT / 2,
                0.20 if openn else (0.26 if i % 2 else 0.14),
                pan=0.22 if i % 2 else -0.22)
        for i in range(4):                          # four-on-the-floor
            add(KICK, t0 + i * BEAT, 0.95 if (heavy or i in (0, 2)) else 0.8)
        add(CLAP, t0 + BEAT, 0.66)
        add(CLAP, t0 + BEAT * 3, 0.66)
        if heavy:
            add(CLAP, t0 + BEAT * 3.75, 0.3)
    else:  # outro
        if b < 14:
            for i in range(8):
                add(HATC, t0 + i * BEAT / 2, 0.18 if i % 2 else 0.10,
                    pan=0.2 if i % 2 else -0.2)
            add(KICK, t0, 0.9)
            add(CLAP, t0 + BEAT * 2, 0.5)

    # ---- bass
    if sec in ("main", "big", "outro") and not (sec == "outro" and b == 14):
        pattern = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
        if sec == "big":
            pattern = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 2.25, 2.5, 3.0, 3.5]
        for off in pattern:
            f = midi(root)
            add(bass(f, BEAT * 0.95), t0 + off * BEAT, gain=0.5, pan=0.0)
            # octave-up layer so it still reads on phone speakers
            add(bass(f * 2, BEAT * 0.5), t0 + off * BEAT, gain=0.26, pan=0.12)

    # ---- hook melody (pluck)
    if sec in ("main", "big", "outro"):
        gain = {"main": 0.34, "big": 0.42, "outro": 0.36}[sec]
        for (beat, note, dur) in MOTIF:
            tt = t0 + beat * BEAT
            if tt >= t0 + BAR:
                continue
            add(pluck(midi(note + BAR_SHIFT[order_idx]), dur * BEAT * 1.5), tt,
                gain=gain, pan=0.18)
            if sec == "big":                        # sparkle octave
                add(pluck(midi(note + BAR_SHIFT[order_idx] + 12), dur * BEAT), tt,
                    gain=0.14, pan=-0.28)

    # ---- transition SFX (timed with the cuts in the video)
    if b == 1:
        add(riser(1.6), t0 + BAR - 1.6, 0.5)

print("[music] arrangement done")

# ---- video-synced SFX (cut times match render_video.py CUTS)
CUTS = [5.30, 7.90, 10.00, 12.20, 15.80, 21.40, 26.50]
for c in CUTS:
    add(whoosh(0.55), c - 0.45, gain=0.5)
    add(blip(660, 0.10), c + 0.02, gain=0.25)
add(boom(46, 1.8), 15.80, gain=0.55)     # CTA hit
add(riser(1.4), 25.05, gain=0.6)         # build into end card
add(boom(52, 2.2), 26.50, gain=0.75)     # end-card slam
add(boom(40, 2.6), 29.10, gain=0.5)      # final hit

# ----------------------------------------------------------------- master
# gentle bus compression + soft limit
env = lp(np.abs(music).max(axis=1), int(SR * 0.02))
music *= (1.0 / (1.0 + 1.6 * env))[:, None]
music = np.tanh(music * 1.25)
music = music / max(1e-9, np.max(np.abs(music))) * 0.89      # ~ -1 dBFS peak

# short stereo widening on the high band for sparkle
mid = music.mean(axis=1, keepdims=True)
side = music - mid
high = side - lp(side[:, 0], 40)[:, None]
music = music + high * 0.35
music = np.clip(music, -1.0, 1.0)

data = (music * 32767.0).astype("<i2")
with wave.open(OUT, "wb") as f:
    f.setnchannels(2)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes(data.tobytes())
print("[music] wrote %s  %.2fs peak=%.3f" % (OUT, DUR, np.max(np.abs(music))))
