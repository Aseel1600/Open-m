#!/usr/bin/env python3
"""
Audio-mix tuning harness for the Mochi Short (no video encode, ~1 s per run).

Renders only the mix for a set of VO / music gain parameters and reports:
  speech    integrated loudness in a window where the VO plays
  musiconly integrated loudness in a window where the bed plays alone
  int       integrated loudness of the whole 30 s
  VO        level of the voice inside the speech window
  bed       level of everything else in that window (energy subtraction)
  VO-bed    separation, i.e. how far the voice sits above the ducked bed

Targets used for the shipped render: voice ~8-10 dB above the ducked bed,
speech/music windows within 3 LU so the bed never jumps, and a final master at
-14 LUFS / <= -1 dBTP (YouTube's reference).

    python3 tune_audio.py
"""
import os
import subprocess
import sys

import numpy as np

try:
    import imageio_ffmpeg

    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:                                     # pragma: no cover
    FF = "ffmpeg"

ROOT = os.path.dirname(os.path.abspath(__file__))
VO = os.path.join(ROOT, "vo")
MUS = os.path.join(ROOT, "audio", "music.wav")
VO_START_MS = [300, 5600, 8150, 10250, 12450, 16050, 21650]
TOTAL = 30.0
SPEECH = (0.6, 4.8)
MUSIC_ONLY = (25.4, 28.0)


def render(vo_pre, vo_makeup, vo_weight, mus_gain, sc_thr, sc_ratio, sc_level,
           out="/tmp/px.wav"):
    fc = []
    for i, ms in enumerate(VO_START_MS):
        fc.append(f"[{i}:a]adelay={ms}|{ms},volume={vo_pre},"
                  f"acompressor=threshold=0.12:ratio=3:attack=6:release=180:"
                  f"makeup={vo_makeup},highpass=f=85,aresample=48000[vo{i+1}]")
    fc.append("".join(f"[vo{i+1}]" for i in range(7)) +
              "amix=inputs=7:normalize=0:dropout_transition=0,"
              f"apad=whole_dur={TOTAL},asplit=2[vo_mix][vo_sc]")
    fc.append(f"[7:a]afade=t=in:st=0:d=0.7,volume={mus_gain}[mus]")
    fc.append(f"[mus][vo_sc]sidechaincompress=threshold={sc_thr}:ratio={sc_ratio}:"
              f"attack=6:release=260:makeup=1:level_sc={sc_level}[musd]")
    fc.append(f"[musd][vo_mix]amix=inputs=2:normalize=0:weights='1 {vo_weight}'[premix]")
    fc.append(f"[premix]apad=whole_dur={TOTAL},afade=t=out:st=28.3:d=1.7,"
              "aresample=48000,aformat=channel_layouts=stereo[out]")
    cmd = [FF, "-y", "-loglevel", "error"]
    for i in range(7):
        cmd += ["-i", os.path.join(VO, f"v{i+1}.mp3")]
    cmd += ["-i", MUS, "-filter_complex", ";".join(fc), "-map", "[out]",
            "-c:a", "pcm_f32le", out]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        print(p.stderr[-1500:])
        sys.exit(1)
    return out


def lufs(path, t0=None, t1=None):
    pre = f"atrim=start={t0}:end={t1},asetpts=N/SR/TB," if t0 is not None else ""
    p = subprocess.run([FF, "-v", "info", "-i", path, "-filter_complex",
                        f"[0:a]{pre}ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    for line in (p.stdout + p.stderr).splitlines():
        if line.strip().startswith("I:"):
            return float(line.split()[1])
    return float("nan")


def analyse(path):
    return lufs(path, *SPEECH), lufs(path, *MUSIC_ONLY), lufs(path)


def energy_sub(total_lufs, voice_lufs):
    """LUFS of everything except the voice inside a window (from energy)."""
    e_t = 10 ** (total_lufs / 10.0)
    e_v = 10 ** (voice_lufs / 10.0)
    rest = e_t - e_v
    return 10 * np.log10(rest) if rest > 1e-12 else -99.0


CANDIDATES = [
    # vo_pre, vo_makeup, vo_weight, music_gain, sc_threshold, sc_ratio, sc_level
    (2.1, 1.0, 1.35, 0.92, 0.030, 7.0, 1.6),   # first attempt: over-ducked
    (2.1, 1.8, 1.35, 0.65, 0.080, 4.0, 1.0),   # shipped configuration
    (2.1, 1.8, 1.35, 0.71, 0.100, 3.0, 0.8),
    (2.1, 2.2, 1.40, 0.71, 0.100, 3.0, 0.9),
]

if __name__ == "__main__":
    vo_only = render(2.1, 1.0, 1.0, 0.0001, 0.03, 7, 1.6, "/tmp/vo_ref.wav")
    vo_ref = lufs(vo_only, *SPEECH)
    print(f"reference: VO stem in {SPEECH} = {vo_ref:.1f} LUFS\n")

    for (vo_pre, vo_mu, vo_w, mus, thr, ratio, lvl) in CANDIDATES:
        render(vo_pre, vo_mu, vo_w, mus, thr, ratio, lvl)
        a, b, c = analyse("/tmp/px.wav")
        v_win = vo_ref + 20 * np.log10(vo_mu * vo_w)
        bed = energy_sub(a, v_win)
        print(f"mus={mus:.2f} vomu={vo_mu:.1f} vow={vo_w:.2f} thr={thr} r={ratio} "
              f"lvl={lvl} | speech={a:6.1f} musiconly={b:6.1f} int={c:6.1f} "
              f"VO={v_win:6.1f} bed={bed:6.1f} VO-bed={v_win - bed:5.1f}dB "
              f"sym={b - a:5.1f}")
