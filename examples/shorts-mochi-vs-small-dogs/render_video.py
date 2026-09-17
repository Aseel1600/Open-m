#!/usr/bin/env python3
"""
Mochi vs Small Dogs - vertical Short renderer (1080x1920, 30 fps, 30.0 s).

Example production for OpenMontage. Zero-API-key, fully local render:

Pass A : Ken-Burns (zoompan) video segment per scene image   -> build/segs/segN.mp4
Pass B : xfade crossfade chain                               -> build/base.mp4
Pass C : Pillow-rendered overlays (captions, tag, pill, end card) + progress bar
         + full audio mix (VO + music bed, sidechain-ducked)  -> mochi_vs_small_dogs_SHORT.mp4

Notes
-----
* The bundled static ffmpeg build has no drawtext (no freetype), so every piece
  of text is baked into an RGBA PNG with Pillow and composited with `overlay`.
* Output targets YouTube's loudness reference: -14 LUFS integrated, <= -1 dBTP.

Rebuild:
    python3 audio/make_music.py     # writes audio/music.wav (needs numpy)
    python3 render_video.py all     # scenes -> crossfades -> captions + audio mix
"""
import os
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageFont

try:
    import imageio_ffmpeg

    FF = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:                                     # pragma: no cover
    FF = "ffmpeg"

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ROOT = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(ROOT, "assets")
VO = os.path.join(ROOT, "vo")
BUILD = os.path.join(ROOT, "build")
SEGS = os.path.join(BUILD, "segs")
OV = os.path.join(BUILD, "ov")
for d in (SEGS, BUILD, OV):
    os.makedirs(d, exist_ok=True)

FPS = 30
W, H = 1080, 1920
XF = 0.25                        # crossfade length
TOTAL = 30.00

WHITE = (255, 255, 255, 255)
YELLOW = (255, 212, 0, 255)
CYAN = (34, 231, 255, 255)
RED = (255, 45, 85, 255)


def run(cmd, label=""):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(f"!! FFMPEG FAILED {label}\n{p.stderr[-4000:]}")
        sys.exit(1)
    return p


# ----------------------------------------------------------------- VO timing
def duration(path):
    w = path.replace(".mp3", ".wav")
    run([FF, "-y", "-loglevel", "error", "-i", path, "-ar", "44100", "-ac", "1",
         "-c:a", "pcm_s16le", w], "vo wav")
    with wave.open(w) as f:
        d = f.getnframes() / f.getframerate()
    os.remove(w)
    return d


# ----------------------------------------------------------------- timeline
CUTS = [0.00, 5.30, 7.90, 10.00, 12.20, 15.80, 21.40, 26.50, 30.00]
IMAGES = ["s1_hook.png", "s2_chihuahua.png", "s3_poodle.png", "s4_pom.png",
          "s5_boss.png", "s6_cta.png", "s7_teaser.png", "s6_cta.png"]
MOTION = [                       # (mode, amount) per segment
    ("in", 0.16), ("out", 0.16), ("panlr", 0.14), ("panrl", 0.14),
    ("in_top", 0.18), ("out", 0.10), ("panud", 0.14), ("in", 0.10),
]

# frame index of every cut, so xfade offsets land exactly on the cuts
CUT_FRAMES = [int(round(c * FPS)) for c in CUTS]
XF_FRAMES = int(round(XF * FPS))
# each segment must run XF past its cut, otherwise xfade has no material to
# dissolve from and the chain stops at the first transition
SEG_FRAMES = [CUT_FRAMES[i + 1] - CUT_FRAMES[i] + (XF_FRAMES if i < 7 else 0)
              for i in range(8)]
SEG_DUR = [f / FPS for f in SEG_FRAMES]
XF_OFFSETS = [CUT_FRAMES[i] / FPS for i in range(1, 8)]
BASE_DUR = sum(SEG_FRAMES) / FPS - 7 * XF
assert all(CUT_FRAMES[i + 1] - CUT_FRAMES[i] > XF_FRAMES for i in range(7))

VO_FILES = [f"v{i}.mp3" for i in range(1, 8)]
VO_START = {"v1.mp3": 0.30, "v2.mp3": 5.60, "v3.mp3": 8.15, "v4.mp3": 10.25,
            "v5.mp3": 12.45, "v6.mp3": 16.05, "v7.mp3": 21.65}

# ----------------------------------------------------------------- captions
# (text, colour, start, end, size, y)   y = top of the text plate
CAPTIONS = [
    ("EVERY DOG OWNER HERE", WHITE, 0.35, 2.55, 78, 1400),
    ("HAS THE SAME NIGHTMARE", WHITE, 2.55, 3.55, 78, 1400),
    ("HAS THE SAME", YELLOW, 3.55, 5.10, 80, 1320),
    ("NIGHTMARE", YELLOW, 4.05, 5.10, 96, 1450),
    ("CHIHUAHUA? GONE.", WHITE, 5.75, 7.85, 88, 1400),
    ("POODLE? SLURPED.", WHITE, 8.30, 9.95, 88, 1400),
    ("POMERANIAN?", WHITE, 10.40, 11.35, 84, 1320),
    ("NOT EVEN CHEWED.", CYAN, 11.35, 12.15, 84, 1450),
    ("NOW MOCHI RUNS", WHITE, 12.70, 14.20, 84, 1360),
    ("THIS NEIGHBORHOOD", YELLOW, 14.20, 15.75, 84, 1470),
    ("LIKE THIS VIDEO", WHITE, 16.30, 18.55, 92, 1400),
    ("SUBSCRIBE", YELLOW, 18.55, 21.30, 104, 1400),
    ("TOMORROW:", WHITE, 22.00, 23.40, 92, 1340),
    ("GOLDEN RETRIEVER", CYAN, 23.40, 25.60, 84, 1470),
    ("PART 2 TOMORROW", WHITE, 27.00, 30.00, 66, 1540),
]
TAG = "MOCHI vs SMALL DOGS"


# ------------------------------------------------------------ PNG text maker
def fit_size(text, size, max_w, stroke):
    """Shrink the font until the stroked text fits inside max_w pixels."""
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    while size > 24:
        font = ImageFont.truetype(FONT_B, size)
        box = meas.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if box[2] - box[0] <= max_w:
            return size
        size -= 2
    return size


def make_png(name, text, size, fill, stroke=9, plate=None, plate_pad=(38, 24),
             radius=30, shadow=True, stroke_fill=(0, 0, 0, 255), max_w=960):
    size = fit_size(text, size, max_w, stroke)
    font = ImageFont.truetype(FONT_B, size)
    meas = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    box = meas.textbbox((0, 0), text, font=font, stroke_width=stroke)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = plate_pad if plate else (stroke + 8, stroke + 8)
    sh = 8 if shadow else 0
    w, h = int(tw + 2 * pad_x + sh), int(th + 2 * pad_y + sh)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if plate:
        d.rounded_rectangle([0, 0, w - 1 - sh, h - 1 - sh], radius=radius, fill=plate)
    tx, ty = pad_x - box[0], pad_y - box[1]
    if shadow:
        d.text((tx + 5, ty + 6), text, font=font, fill=(0, 0, 0, 165),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 165))
    d.text((tx, ty), text, font=font, fill=fill, stroke_width=stroke,
           stroke_fill=stroke_fill)
    path = os.path.join(OV, name + ".png")
    img.save(path)
    return path, w, h


def build_overlays():
    """Returns list of overlay dicts: path / x / y / enable / optional pre-filter."""
    ovs = []

    # captions
    for i, (txt, color, t0, t1, size, y) in enumerate(CAPTIONS):
        p, _, _ = make_png(f"cap{i}", txt, size, color, stroke=10,
                           plate=(0, 0, 0, 150))
        ovs.append(dict(path=p, x="(main_w-overlay_w)/2", y=y,
                        enable=f"between(t,{t0},{t1})"))

    # persistent corner tag (white, then yellow during the end card)
    p, _, _ = make_png("tag_w", TAG, 46, WHITE, stroke=0, max_w=560,
                       plate=(0, 0, 0, 140), plate_pad=(26, 14), radius=20,
                       shadow=False)
    ovs.append(dict(path=p, x=48, y=140, enable="between(t,0.15,26.30)"))
    p, _, _ = make_png("tag_y", TAG, 46, YELLOW, stroke=0, max_w=560,
                       plate=(0, 0, 0, 140), plate_pad=(26, 14), radius=20,
                       shadow=False)
    ovs.append(dict(path=p, x=48, y=140, enable="between(t,26.40,30)"))

    # cold-open bang: MEET MOCHI (slides up; alpha stepped instead of fade,
    # because a still overlay has a single frame so timeline fades never run)
    p, _, _ = make_png("bang", "MEET MOCHI", 150, WHITE, stroke=14, plate=None,
                       shadow=True, max_w=980)
    y_expr = "'if(lt(t,0.35), 520+(0.35-t)*1500, 520)'"
    for k, (t0, t1, a) in enumerate([(0.05, 0.14, 0.35), (0.14, 0.23, 0.65),
                                     (0.23, 1.30, 1.00), (1.30, 1.42, 0.78),
                                     (1.42, 1.54, 0.56), (1.54, 1.66, 0.36),
                                     (1.66, 1.78, 0.18), (1.78, 1.90, 0.05)]):
        ovs.append(dict(path=p, x="(main_w-overlay_w)/2", y=y_expr,
                        enable=f"between(t,{t0},{t1})",
                        pre=f"format=rgba,colorchannelmixer=aa={a}"))

    # pulsing SUBSCRIBE pill
    p, _, _ = make_png("pill", "SUBSCRIBE", 62, WHITE, stroke=0, max_w=820,
                       plate=(255, 45, 85, 242), plate_pad=(60, 26), radius=60,
                       shadow=True)
    ovs.append(dict(path=p, x="(main_w-overlay_w)/2", y="'600+8*sin(9*t)'",
                    enable="between(t,18.45,21.45)"))

    # end-card CTA bar
    p, _, _ = make_png("end1", "LIKE  +  SUBSCRIBE", 92, WHITE, stroke=12,
                       plate=(0, 0, 0, 140), plate_pad=(46, 26), radius=26,
                       max_w=930)
    ovs.append(dict(path=p, x="(main_w-overlay_w)/2", y=1210,
                    enable="between(t,26.60,30)"))
    return ovs


# ============================================================ PASS A: scenes
def build_segments():
    for i, (img, (mode, amt), d) in enumerate(zip(IMAGES, MOTION, SEG_FRAMES), start=1):
        z, x, y = "", "", ""
        if mode == "in":
            z = f"1+{amt}*on/{d}"
        elif mode == "out":
            z = f"{1 + amt}-{amt}*on/{d}"
        elif mode == "panlr":
            z = f"{1 + amt}"; x = f"(iw-iw/zoom)*(on/{d})"
        elif mode == "panrl":
            z = f"{1 + amt}"; x = f"(iw-iw/zoom)*(1-on/{d})"
        elif mode == "panud":
            z = f"{1 + amt}"; y = f"(ih-ih/zoom)*(on/{d})"
        elif mode == "in_top":
            z = f"1+{amt}*on/{d}"; y = "(ih-ih/zoom)*0.18"
        vf = (f"scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,"
              f"crop={2 * W}:{2 * H},"
              f"zoompan=z='{z}':x='{x or 'iw/2-(iw/zoom)/2'}':"
              f"y='{y or 'ih/2-(ih/zoom)/2'}':d={d}:s={W}x{H}:fps={FPS},"
              f"setsar=1,format=yuv420p")
        out = os.path.join(SEGS, f"seg{i}.mp4")
        run([FF, "-y", "-loglevel", "error", "-i", os.path.join(ASSETS, img),
             "-vf", vf, "-frames:v", str(d), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "16", "-r", str(FPS), "-pix_fmt", "yuv420p", out], f"seg{i}")
        print(f"[A] seg{i} {img:18s} {mode:7s} {d} frames ({d / FPS:.2f}s)")


# ========================================================= PASS B: crossfades
def build_base():
    inputs, chains = [], []
    for i in range(1, 9):
        inputs += ["-i", os.path.join(SEGS, f"seg{i}.mp4")]
    prev = "0:v"
    for i, offset in enumerate(XF_OFFSETS, start=1):
        chains.append(f"[{prev}][{i}:v]xfade=transition=fade:duration={XF}:"
                      f"offset={offset:.3f}[x{i}]")
        prev = f"x{i}"
    run([FF, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
         "-map", f"[{prev}]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), os.path.join(BUILD, "base.mp4")], "xfade")
    print(f"[B] crossfade chain built -> build/base.mp4 ({BASE_DUR:.2f}s, "
          f"offsets {XF_OFFSETS})")


# ==================================================== PASS C: overlays + audio
def build_final():
    ovs = build_overlays()
    print(f"[C] rendered {len(ovs)} overlay PNGs")

    inputs = ["-i", os.path.join(BUILD, "base.mp4")]
    for o in ovs:                    # single-frame PNG: overlay repeats it (framesync)
        inputs += ["-i", o["path"]]
    for f in VO_FILES:
        inputs += ["-i", os.path.join(VO, f)]
    inputs += ["-i", os.path.join(ROOT, "audio", "music.wav")]

    fc, cur = [], "0:v"
    for i, o in enumerate(ovs, start=1):
        src = f"{i}:v"
        if o.get("pre"):
            fc.append(f"[{src}]{o['pre']}[o{i}]")
            src = f"o{i}"
        fc.append(f"[{cur}][{src}]overlay=x={o['x']}:y={o['y']}:"
                  f"enable='{o['enable']}'[v{i}]")
        cur = f"v{i}"
    # loading-style progress bar pinned to the top edge (drawn last: stays on top)
    fc.append(f"[{cur}]drawbox=x=0:y=0:w='{W}*min(t/{TOTAL},1)':h=10:"
              f"color=0xFFD400@0.95:t=fill[vout]")

    # ---------------- audio graph ----------------
    base_i = 1 + len(ovs)
    vo_specs = []
    for k, f in enumerate(VO_FILES):
        idx = base_i + k
        ms = int(round(VO_START[f] * 1000))
        fc.append(f"[{idx}:a]adelay={ms}|{ms},volume=2.1,"
                  f"acompressor=threshold=0.12:ratio=3:attack=6:release=180:"
                  f"makeup=1.8,highpass=f=85,aresample=48000[vo{k + 1}]")
        vo_specs.append(f"[vo{k + 1}]")
    fc.append(f"{''.join(vo_specs)}amix=inputs={len(VO_FILES)}:normalize=0:"
              f"dropout_transition=0[voall]")
    # pad the VO bus to the full 30 s: sidechaincompress stops when its
    # sidechain ends, which would truncate the whole mix
    fc.append(f"[voall]apad=whole_dur={TOTAL}[voallp]")
    fc.append("[voallp]asplit=2[vo_mix][vo_sc]")
    fc.append(f"[{base_i + len(VO_FILES)}:a]afade=t=in:st=0:d=0.7,volume=0.65[mus]")
    fc.append("[mus][vo_sc]sidechaincompress=threshold=0.080:ratio=4:attack=6:"
              "release=260:makeup=1:level_sc=1.0[musd]")
    fc.append("[musd][vo_mix]amix=inputs=2:normalize=0:weights='1 1.35'[premix]")
    # post-mix makeup so the master lands on YouTube's -14 LUFS reference
    fc.append("[premix]volume=0.90[premix2]")
    fc.append(f"[premix2]apad=whole_dur={TOTAL},afade=t=out:st=28.3:d=1.7,"
              "alimiter=level=disabled:limit=0.72:attack=5:release=50,"
              "aresample=48000,aformat=channel_layouts=stereo[aout]")

    fs_path = os.path.join(BUILD, "filters.txt")
    with open(fs_path, "w") as fh:
        fh.write(";".join(fc))

    cmd = [FF, "-y", "-loglevel", "error", *inputs,
           "-filter_complex_script", fs_path,
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19",
           "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-g", "60",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-t", str(TOTAL), "-movflags", "+faststart",
           "-metadata", "title=Mochi vs Small Dogs #shorts",
           os.path.join(ROOT, "mochi_vs_small_dogs_SHORT.mp4")]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("!! FINAL PASS FAILED\n", p.stderr[-6000:])
        sys.exit(1)
    print("[C] overlays + audio mixed -> mochi_vs_small_dogs_SHORT.mp4")


# ------------------------------------------------------------ VO duration log
if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "d"):
        for f in VO_FILES:
            print(f"    {f} {duration(os.path.join(VO, f)):.2f}s")
    if stage in ("all", "a"):
        build_segments()
    if stage in ("all", "b"):
        build_base()
    if stage in ("all", "c"):
        build_final()
