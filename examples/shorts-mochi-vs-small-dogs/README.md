# "Mochi vs Small Dogs" — a 30 s vertical Short, zero API keys

A complete, self-contained example production: an AI-illustrated comedy Short in
1080×1920, built entirely with local tools (Pillow + FFmpeg + numpy). No paid
provider, no render runtime, no agent loop — just a reproducible render script.

**Deliverable:** [`mochi_vs_small_dogs_SHORT.mp4`](mochi_vs_small_dogs_SHORT.mp4)

| Spec | Value |
|---|---|
| Resolution | 1080 × 1920 (9:16 vertical — Shorts / Reels / TikTok) |
| Duration | 30.00 s @ 30 fps |
| Video | H.264 High, yuv420p, `+faststart`, ~5.5 Mbps |
| Audio | AAC-LC 48 kHz stereo, ~204 kbps |
| Loudness | **-14.7 LUFS integrated, -2.5 dBFS true peak** (YouTube's -14 LUFS reference, no clipping) |

## What it demonstrates

- **Ken-Burns scene animation** from still images (`zoompan`) with per-scene motion
  modes (push in/out, lateral and vertical pans) instead of a static slideshow.
- **Exactly-timed crossfades** (`xfade`) driven by a frame-indexed cut list.
- **Burned-in captions without `drawtext`**: the bundled static FFmpeg build has no
  freetype, so every headline is rendered to an RGBA PNG with Pillow (auto-fitted to
  the frame, with plate, stroke and drop shadow) and composited via `overlay`.
- **Reactive overlays**: pulsing SUBSCRIBE pill (`sin(t)` on the y expression), a
  loading-bar style progress indicator, a persistent corner tag, and a cold-open
  title that slides up then alpha-steps out.
- **A synthesized soundtrack** (`audio/make_music.py`): 30 s bed in C minor at 120 BPM
  with kick/clap/hats/bass/pluck hook/pad plus risers, whooshes and impact booms
  timed to the cut list. Pure numpy — no samples, no licensing.
- **A broadcast-style audio mix**: VO compression and high-pass, a music bed ducked
  under the voice with `sidechaincompress`, then a makeup stage that lands the
  master on -14 LUFS with a true-peak ceiling below -1 dBFS.
- **An offline tuning harness** (`tune_audio.py`) that measures speech-vs-bed
  separation in LU so the mix is tuned from data instead of by ear.

## Rebuild it

```bash
pip install numpy pillow imageio-ffmpeg

python3 audio/make_music.py     # -> audio/music.wav        (30 s original score)
python3 render_video.py all     # -> mochi_vs_small_dogs_SHORT.mp4 (~2.5 min on 2 cores)
```

Stages can be run individually — `python3 render_video.py a|b|c|d` — so you can
iterate on the caption pass without re-rendering the scenes. Only `music.wav` and
`build/` are regenerated; both are gitignored.

Tune the mix (audio only, ~1 s per candidate):

```bash
python3 tune_audio.py
```

## Pipeline

```
assets/s*.png ──▶ [A] zoompan  ──▶ build/segs/seg*.mp4
                                        │
                                        ▼
                                   [B] xfade chain ──▶ build/base.mp4
                                        │
vo/v*.mp3 ──────┐                       ▼
audio/music.wav ┴▶ [C] overlays + drawbox + amix/sidechain ──▶ mochi_vs_small_dogs_SHORT.mp4
```

Three engineering details that this example works around, worth knowing before
you fork it:

1. **`xfade` needs tail frames.** Each segment must extend past its cut by at
   least the crossfade duration, otherwise the chain has nothing to dissolve from
   and silently stops after the first transition (it produced a 5.7 s "30 s" file
   before this was fixed — see `SEG_FRAMES` in `render_video.py`).
2. **`sidechaincompress` truncates at the end of its sidechain.** The VO bus is
   padded to the full duration with `apad=whole_dur`, otherwise the entire mix
   dies when the last voice line ends.
3. **`alimiter` auto-levels unless told otherwise.** `level=disabled` is required
   for the limiter to act as a plain ceiling while the mix keeps its intended gain.

## Files

```
mochi_vs_small_dogs_SHORT.mp4   the deliverable (30 s, 21 MB)
render_video.py                 full 3-pass pipeline (scenes → crossfade → captions + mix)
audio/make_music.py             numpy soundtrack generator
tune_audio.py                   LUFS-based mix tuning harness
YOUTUBE_UPLOAD.md               titles, description, hashtags, upload checklist
assets/                         7 illustrated scenes (generated, 9:16)
vo/                             7 voiceover lines (synthesized)
build/, audio/music.wav         regenerable intermediates (gitignored)
```

## Assets & disclosure

- Illustrations and voiceover are **AI-generated** for this example; the soundtrack
  is synthesized from scratch by `audio/make_music.py`. Nothing is licensed
  third-party media, so the example is safe to publish as-is.
- The comedy is deliberately slapstick: dogs vanish in cartoon "POOF" clouds and
  nothing is shown being harmed, which keeps it advertiser-safe on Shorts/Reels.
- YouTube asks creators to disclose **realistic synthetic voice** in the upload
  flow ("Altered content"). Tick that box if you publish this render.
