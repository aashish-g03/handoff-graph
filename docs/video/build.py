"""Assemble the demo video: per-shot cuts timed to narration, zooms, captions, fades, cards."""
import json, re, subprocess, sys
from pathlib import Path

V = Path(__file__).parent
FPS = 30
N = json.load(open(V / "narration.json"))
PLAIN = "--plain" in sys.argv  # no zooms (fallback)


def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                capture_output=True, text=True).stdout)


# shot: source, start, audio key, audio delay, tail pad, zoom keyframes [(t, z, cx, cy)]
CON = (1234, 500)       # decision console in the hero
SHOTS = [
    ("s1", "page", 1.0, "s1", 0.3, 0.6, [(0, 1.0, 960, 540), (20.5, 1.12, 900, 470)]),
    ("s2a", "page", 18.06, "s2a", 0.2, 0.6, [(0, 1.0, 960, 540), (3.2, 1.0, 960, 540), (4.6, 1.55, *CON), (18.6, 1.55, *CON)]),
    ("s2b", "page", 39.16, "s2b", 1.6, 0.6, [(0, 1.0, 960, 540), (3.4, 1.0, 960, 540), (4.8, 1.55, 1234, 430), (12.5, 1.55, 1234, 430)]),
    ("s2c", "page", 53.33, "s2c", 1.6, 0.6, [(0, 1.0, 960, 540), (3.4, 1.0, 960, 540), (4.8, 1.55, 1234, 440), (16.0, 1.55, 1234, 440)]),
    ("s3", "browser", 8.63, "s3", 0.4, 0.6, [(0, 1.0, 960, 540), (4.0, 1.0, 960, 540), (6.0, 1.7, 1155, 573), (25.5, 1.7, 1155, 573)]),
    ("s4", "page", 72.48, "s4", 0.4, 0.8, [(0, 1.0, 960, 540), (8.5, 1.0, 960, 540), (10.0, 1.75, 673, 560), (29.3, 1.75, 673, 560), (31.3, 1.75, 1250, 560), (34.0, 1.75, 1250, 560), (35.3, 1.0, 960, 540)]),
    ("s5", "page", 110.24, "s5", 0.4, 0.6, [(0, 1.0, 960, 540), (2.5, 1.0, 960, 540), (4.0, 1.3, 960, 500), (19.5, 1.3, 960, 500)]),
    ("s6", "page", 137.74, "s6", 0.3, 1.2, [(0, 1.0, 960, 540), (2.8, 1.0, 960, 540), (4.2, 1.6, 760, 300), (14.0, 1.6, 760, 300)]),
]


def piecewise(keys, idx, T="t"):
    """Smoothstep-interpolated expression of t over keyframes; idx 1=z, 2=cx, 3=cy."""
    expr = str(keys[-1][idx])
    for (t0, *a), (t1, *b) in reversed(list(zip(keys, keys[1:]))):
        v0, v1 = a[idx - 1], b[idx - 1]
        s = f"(clip(({T}-{t0})/{max(t1 - t0, 0.001)},0,1))"
        seg = f"({v0}+({v1}-{v0})*{s}*{s}*(3-2*{s}))"
        expr = f"if(lt({T},{t1}),{seg},{expr})"
    return f"if(lt({T},{keys[0][0]}),{keys[0][idx]},{expr})"


def ass_time(s):
    h, m = int(s // 3600), int(s % 3600 // 60)
    return f"{h}:{m:02d}:{s % 60:05.2f}"


def captions(key, delay, adur, out):
    text = re.sub(r"\[[^\]]*\]\s*", "", N[key]).replace("...", ",").replace(" ,", ",")
    parts = [p.strip() for p in re.split(r"(?<=[.?!:])\s+", text) if p.strip()]
    # split long sentences at commas
    lines = []
    for p in parts:
        if len(p) > 70 and "," in p:
            bits, cur = p.split(","), ""
            for b in bits:
                if cur and len(cur) + len(b) > 60:
                    lines.append(cur.strip(" ,") + ","); cur = b
                else:
                    cur = (cur + "," + b) if cur else b
            lines.append(cur.strip(" ,"))
        else:
            lines.append(p)
    total = sum(len(l) for l in lines)
    t, ev = delay, []
    for l in lines:
        d = adur * len(l) / total
        ev.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + d)},Cap,,0,0,0,,{l.rstrip(',')}")
        t += d
    out.write_text("""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0101418,0,0,0,0,100,100,0,0,3,14,0,2,200,200,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2500:]); sys.exit(1)


seg_files = []
card = lambda name, d: (V / "cards" / f"{name}.png", d)
for name, d in [("title", 4.0)]:
    png, D = card(name, d)
    out = V / "out" / f"seg_{name}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(D), "-i", str(png), "-f", "lavfi", "-t", str(D), "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", f"fps={FPS},format=yuv420p,fade=in:st=0:d=0.5,fade=out:st={D - 0.4}:d=0.4", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
    seg_files.append(out)

for key, src, start, akey, delay, tail, keys in SHOTS:
    a = V / "audio" / f"{akey}.mp3"
    ad = dur(a)
    D = round(delay + ad + tail, 2)
    ass = V / "out" / f"{key}.ass"
    captions(akey, delay, ad, ass)
    if PLAIN:
        zoom = "scale=1920:1080"
    else:
        T = f"(in/{FPS})"
        Z = piecewise(keys, 1, T); CX = piecewise(keys, 2, T); CY = piecewise(keys, 3, T)
        # upscale 2x first so zoompan's integer offsets don't jitter, then zoom to a fixed 1080p output
        zoom = (f"scale=3840:2160:flags=lanczos,zoompan=z='{Z}':d=1:s=1920x1080:fps={FPS}:"
                f"x='clip(({CX})*2-iw/zoom/2,0,iw-iw/zoom)':y='clip(({CY})*2-ih/zoom/2,0,ih-ih/zoom)'")
    vf = (f"[0:v]fps={FPS},setpts=PTS-STARTPTS,{zoom},subtitles={ass}:fontsdir=/System/Library/Fonts,"
          f"fade=in:st=0:d=0.35,fade=out:st={D - 0.35}:d=0.35,format=yuv420p[v];"
          f"[1:a]adelay={int(delay * 1000)}:all=1,apad,atrim=0:{D},afade=out:st={D - 0.3}:d=0.3[a]")
    out = V / "out" / f"seg_{key}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-ss", str(start), "-t", str(D), "-i", str(V / "clips" / f"{src}.webm"), "-i", str(a),
         "-filter_complex", vf, "-map", "[v]", "-map", "[a]", "-t", str(D), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2", str(out)])
    print(key, "audio", round(ad, 1), "segment", D)
    seg_files.append(out)

for name, d in [("end", 6.0)]:
    png, D = card(name, d)
    out = V / "out" / f"seg_{name}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(D), "-i", str(png), "-f", "lavfi", "-t", str(D), "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", f"fps={FPS},format=yuv420p,fade=in:st=0:d=0.4,fade=out:st={D - 0.8}:d=0.8", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)])
    seg_files.append(out)

lst = V / "out" / "list.txt"
lst.write_text("".join(f"file '{f}'\n" for f in seg_files))
final = V / "out" / ("handoff-graph-demo-plain.mp4" if PLAIN else "handoff-graph-demo.mp4")
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(final)])
print("final", final, round(dur(final), 1), "s")
