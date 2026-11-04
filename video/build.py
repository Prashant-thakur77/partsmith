"""The PartSmith film editor: one scene list in, one finished film out. Nothing is hand-placed on a timeline.

    python3 video/build.py timeline   ->  build/timeline.json (scene starts from the real voice takes)
    python3 video/build.py stills     ->  stills/ (frames the recap uses, cut from the real recordings)
    python3 video/build.py gfx        ->  records every drawn scene (graphics.html / three.html) to its exact length
    python3 video/build.py film       ->  final/PartSmith-film.mp4, a 720p copy, captions (.ass burned, .srt) and chapters
    python3 video/build.py storyboard ->  video/storyboard.md, generated from the scene list and the timeline
    python3 video/build.py check      ->  length, stream lengths, loudness, gaps with no voice, word match against the script

Inputs: audio/lines/*.wav and audio/words.json (video/synth.py), clips/*.mp4 (video/record.mjs <flow>),
build/facts.json (video/facts.py), music (video/music.py) and sfx (video/sfx.py), all under ~/Videos/partsmith.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from narration import WORK, load  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
FPS = 30
PAPER = "0xfaf7f1"
PIP_W, PIP_H = 560, 630
PIP = {"vision": "f3", "end": "f2"}  # the founder in a bubble over these drawn scenes, saying that line
CLIPS = f"{WORK}/clips"
BUILD = f"{WORK}/build"
FINAL = f"{WORK}/final"
FONTS = os.path.expanduser("~/Videos/partsmith/fonts")

TEST_LINES = [lid for scene, lid, *_ in load() if scene == "test"]

# name, lines, visual, chapter, extra hold (s), minimum length (s)
# clip visual: ("clip", flow, start mark, speed, {"push": [t0, t1, zoom, cx, cy]}); pushes ease in on the element in use.
SCENES = [
    ("open", ["n01", "n02", "n03", "n04", "n05", "n07"], ("gfx",), "The problem", 0.15, 0),
    ("title", ["n08"], ("gfx",), "PartSmith", 0.2, 0),
    ("founder", ["f1"], ("face", "f1"), "PartSmith", 0.1, 0),
    ("flow", ["w2", "w3", "w4"], ("gfx",), "The flow", 0.35, 0),
    ("mat", ["n09"], ("clip", "calibrate", "start", 1.0, {"push": [0.1, 1.0, 1.35, 0.32, 0.42]}), "The screen is the ruler", 0.05, 0),
    ("photo", ["n11"], ("clip", "calibrate", "mat", 1.0), "The screen is the ruler", 0.05, 0),
    ("see", ["v2", "v3", "v4"], ("gfx",), "How it sees", 0.3, 0),
    ("loop0", ["n13"], ("clip", "replay", "write-0.2", 1.0, {"push": [0.1, 0.9, 1.7, 0.75, 0.4]}), "The loop", 0.05, 0),
    ("loop", ["n14", "n15", "n16"], ("gfx",), "The loop", 0.5, 0),
    ("export", ["n16b"], ("clip", "job", "verified", 1.0, {"push": [0.5, 1.5, 1.4, 0.72, 0.42]}), "The loop", 0.1, 0),
    ("lie", ["n18", "n19", "n20"], ("clip", "lie", "start+1.2", 1.2, {"push": [0.1, 1.1, 1.45, 0.33, 0.42]}), "The risky case", 0.15, 0),
    ("knobs", ["n21"], ("clip", "knobs", "open", 3.0, {"push": [0.1, 0.6, 1.3, 0.55, 0.5]}), "Edit and fit", 0.1, 2.2),
    ("say0", ["s0"], ("clip", "say", "start", 1.0, {"push": [0.1, 0.9, 1.7, 0.59, 0.36]}), "Edit and fit", 0.0, 0),
    ("say", ["say1", "s2"], ("clip", "say", "talk", "fit:18.2", {"push": [0.0, 0.1, 1.7, 0.59, 0.36]}), "Edit and fit", 0.2, 0),
    ("fit", ["n22"], ("clip", "fit", "start", 1.0, {"push": [0.1, 1.0, 1.55, 0.3, 0.35]}), "Edit and fit", 0.05, 2.2),
    ("review", ["n23"], ("clip", "review", "start", 1.0, {"push": [0.1, 1.0, 1.4, 0.65, 0.45]}), "Review and registry", 0.05, 0),
    ("registry", ["n24"], ("clip", "registry", "start", 2.6), "Review and registry", 0.1, 0),
    ("others", ["c2", "c3", "c4"], ("gfx",), "What people use today", 0.35, 0),
    ("before", ["b2"], ("gfx",), "What was not possible", 0.3, 0),
    ("hood", ["m1", "m2", "m3", "m4", "m7"], ("gfx", "three"), "How Meta made it possible", 0.15, 0),
    ("meta", ["m5"], ("gfx",), "How Meta made it possible", 0.5, 0),
    ("saves", ["e1", "e3", "e4"], ("gfx",), "Time and why it works", 0.3, 0),
    ("test", TEST_LINES, ("gfx",), "Testing", 0.5, 0),
    ("market", ["k1", "k2"], ("gfx",), "Market and vision", 0.25, 0),
    ("vision", ["v9", "f3"], ("gfx",), "Market and vision", 0.3, 0),
    ("close", ["n37", "n38"], ("gfx",), "", 0.2, 0),
    ("end", ["f2"], ("gfx",), "", 2.4, 0),
]
LEAD = 0.12
LABELS = {
    "mat": "Real app · calibration screen · slowed to ×{speed}",
    "photo": "Real app · the mat at true scale",
    "loop0": "Recorded live run · rendered sample photo · slowed to ×{speed}",
    "export": "Recorded live run · the one export gate",
    "model": "Real app · 3D view of the verified model",
    "say0": "Real app · live call to Muse Voice Transcribe",
    "say": "Live Muse Voice Transcribe · test line in the narrator's voice · sped up ×{speed}",
    "cost": "Same run · print figures are estimates, not a quote",
    "lie": "Scripted attack · no model call · real verifier",
    "knobs": "Real app · sped up ×{speed}",
    "fit": "Labelled example, not a measurement",
    "review": "Scripted test review, not a person's",
    "registry": "Real app · local server · sped up ×{speed}",
}
FOUNDER = f"{WORK}/founder"


def founder_clip(lid: str) -> str | None:
    """The founder's own take of a line (FOUNDER_SCRIPT.md), when one has been recorded."""
    for ext in ("mp4", "mov", "mkv", "webm"):
        path = f"{FOUNDER}/{lid}.{ext}"
        if os.path.exists(path):
            return path
    return None


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def gap(text: str, scene: str) -> float:
    if scene == "recap":
        return 0.32
    return 0.36 if text.rstrip().endswith("?") else 0.24


def timeline() -> dict:
    lines = {lid: (scene, caption) for scene, lid, caption, *_ in load()}
    info = json.load(open(f"{WORK}/audio/lines.json"))
    t = 0.0
    scenes = []
    for name, ids, visual, chapter, hold, minimum in SCENES:
        start = t
        cur = t + LEAD
        out = []
        for i, lid in enumerate(ids):
            out.append({"id": lid, "start": round(cur, 3), "dur": info[lid]["s"], "caption": lines[lid][1]})
            cur += info[lid]["s"] + (gap(lines[lid][1], name) if i < len(ids) - 1 else 0)
        end = max(cur + hold, start + minimum)
        # A long scene spreads its spare time between the lines instead of holding at the end.
        if minimum and end - (cur + hold) > 0 and len(out) > 1:
            spare = (end - (cur + hold)) / len(out)
            for i, l in enumerate(out):
                l["start"] = round(l["start"] + spare * i, 3)
        dur = round(round((end - start) * FPS) / FPS, 4)
        scenes.append({"name": name, "start": round(start, 3), "dur": dur, "chapter": chapter, "visual": list(visual),
                       "lines": [{**l, "start": round(l["start"] - start, 3)} for l in out]})
        t = start + dur
    for s in scenes:
        if s["name"] == "hood":
            c = {l["id"]: l for l in s["lines"]}
            m2, m3, m4, m7 = c["m2"]["start"], c["m3"]["start"], c["m4"]["start"], c["m7"]["start"]
            s["cues"] = {"photo": 0.1, "sam": m2, "measure": m2 + 1.2, "satellites": m3, "agent": m4, "sandbox": m4 + 0.8, "verifier": m4 + 1.2,
                         "blocked": m7, "human": m7 + 0.8, "registry": m7 + 1.4, "final": s["dur"] - 0.6}
    tl = {"total": round(t, 3), "scenes": scenes}
    os.makedirs(BUILD, exist_ok=True)
    json.dump(tl, open(f"{BUILD}/timeline.json", "w"), indent=1)
    for s in scenes:
        print(f"{s['start']:7.2f}  {s['dur']:5.2f}s  {s['name']}")
    print("total", round(t, 2), "s")
    return tl


def mark(flow: str, spec) -> float:
    if isinstance(spec, (int, float)):
        return float(spec)
    marks = json.load(open(f"{CLIPS}/{flow}.marks.json"))
    m = re.match(r"(\w+)([+-][\d.]+)?", spec)
    return marks[m.group(1)] + float(m.group(2) or 0)


def frame(src: str, at: float, out: str) -> None:
    run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(at), "-i", src, "-frames:v", "1", "-q:v", "3", out])


def stills() -> None:
    """Frames for the recap, each cut from the real recording it stands for."""
    d = f"{WORK}/stills"
    os.makedirs(d, exist_ok=True)
    picks = [("market", "registry", "start+1.5"), ("flow-review", "review", "start+2")]
    for name, flow, at in picks:
        frame(f"{CLIPS}/{flow}.mp4", mark(flow, at), f"{d}/{name}.jpg")
    print("stills in", d)


def gfx(only: set[str]) -> None:
    tl = json.load(open(f"{BUILD}/timeline.json"))
    for s in tl["scenes"]:
        if (s["visual"][0] == "gfx" or (s["visual"][0] == "face" and not founder_clip(s["visual"][1]))) and (not only or s["name"] in only):
            run(["node", f"{ROOT}/video/record.mjs", f"gfx-{s['name']}"])


def drawtext(text: str) -> str:
    font = f"{FONTS}/Geist-SemiBold.ttf"
    t = text.replace(":", r"\:").replace("'", "\u2019")
    return (f"drawtext=fontfile={font}:text='{t}':x=48:y=h-52-th:fontsize=28:fontcolor=0x1c2230:"
            "box=1:boxcolor=0xffffff@0.92:boxborderw=12")


def lower_third(name: str, role: str) -> str:
    bold, plain = f"{FONTS}/Geist-SemiBold.ttf", f"{FONTS}/Geist-Regular.ttf"
    return (f"drawbox=x=70:y=720:w=620:h=128:color=0xfaf7f1@0.96:t=fill,drawbox=x=70:y=720:w=8:h=128:color=0xe8590c:t=fill,"
            f"drawtext=fontfile={bold}:text='{name}':x=100:y=734:fontsize=50:fontcolor=0x1c2230,"
            f"drawtext=fontfile={plain}:text='{role}':x=100:y=796:fontsize=32:fontcolor=0x5b6170")


def bubble_mask() -> str:
    """The founder's rounded picture-in-picture shape."""
    path = f"{BUILD}/bubble-mask.png"
    if not os.path.exists(path):
        w, h, r = PIP_W, PIP_H, 36
        cond = (f"lte(pow(max(max({r}-X,X-({w}-{r}-1)),0),2)+pow(max(max({r}-Y,Y-({h}-{r}-1)),0),2),{r}*{r})")
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=white:s={w}x{h},format=gray", "-vf", f"geq=lum='255*{cond}'", "-frames:v", "1", path])
    return path


def paper_fade() -> str:
    """A transparent-to-paper ramp over the bottom of the frame."""
    path = f"{BUILD}/paper-fade.png"
    if not os.path.exists(path):
        run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0xfaf7f1:s=1920x1080,format=rgba",
             "-vf", "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255*0.94*clip((Y-760)/190,0,1)'", "-frames:v", "1", path])
    return path


def render_scene(s: dict) -> str:
    out = f"{BUILD}/scene-{s['name']}.mp4"
    dur = s["dur"]
    kind = s["visual"][0]
    if kind == "gfx":
        src = f"{CLIPS}/gfx-{s['name']}.mp4"
        start = json.load(open(f"{CLIPS}/gfx-{s['name']}.marks.json"))["start"]
        speed = 1.0
        label = ""
    elif kind == "face":
        clip = founder_clip(s["visual"][1])
        if clip:
            # The founder on camera: the whole frame, the take's own timing (never sped up).
            third = lower_third("Prashant", "Solo builder · Indie track")
            vf = [f"fps={FPS}", "scale=1920:1280", "crop=1920:1080:0:40", third,
                  f"tpad=stop_mode=clone:stop_duration={dur + 2}", f"trim=duration={dur}", "setpts=PTS-STARTPTS",
                  f"fade=t=in:st=0:d=0.16:c={PAPER}", f"fade=t=out:st={max(dur - 0.16, 0):.3f}:d=0.16:c={PAPER}", "format=yuv420p"]
            run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{json.load(open(f'{WORK}/audio/lines.json'))[s['visual'][1]].get('from', 0)}", "-i", clip,
                 "-vf", ",".join(vf), "-an", "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-r", str(FPS), out])
            return out
        src = f"{CLIPS}/gfx-{s['name']}.mp4"
        start = json.load(open(f"{CLIPS}/gfx-{s['name']}.marks.json"))["start"]
        speed = 1.0
        label = ""
    else:
        _, flow, at, speed, *opts = s["visual"]
        push = (opts[0] if opts else {}).get("push")
        src = f"{CLIPS}/{flow}.mp4"
        start = mark(flow, at)
        if isinstance(speed, str) and speed.startswith("fit:"):
            speed = round(min(3.0, max(1.0, (float(speed[4:]) - start) / dur)), 2)
        label = LABELS.get(s["name"], "").replace("{speed}", f"{speed:g}")
        if speed < 1 and "{speed}" not in LABELS.get(s["name"], "") and label:
            label += f" · slowed to ×{speed:g}"
    vf = [f"setpts=(PTS-STARTPTS)/{speed}", f"fps={FPS}", "scale=1920:1080:flags=lanczos",
          f"tpad=stop_mode=clone:stop_duration={dur + 2}"]
    # A slow 1 → 1.03 push so a held screen is never quite still.
    if kind == "clip" and push:
        # An eased push (cubic ease-out) from the full frame to (cx, cy) at zoom z between t0 and t1, on a 2x upscale.
        t0, t1, z, cx, cy = push
        e = f"(1-pow(1-clip((on/{FPS}-{t0})/{t1 - t0},0,1),3))"
        vf[2] = "scale=3840:2160:flags=lanczos"
        vf.append(f"zoompan=z='1+{z - 1}*{e}':x='clip({e}*({cx}*iw-iw/zoom/2)+(1-{e})*(iw/2-iw/zoom/2),0,iw-iw/zoom)'"
                  f":y='clip({e}*({cy}*ih-ih/zoom/2)+(1-{e})*(ih/2-ih/zoom/2),0,ih-ih/zoom)':d=1:s=1920x1080:fps={FPS}")
    elif kind == "clip":
        vf.append(f"zoompan=z='1+0.03*on/({dur}*{FPS})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps={FPS}")
    if label:
        vf.append(drawtext(label))
    vf += [f"trim=duration={dur}", "setpts=PTS-STARTPTS", f"fade=t=in:st=0:d=0.16:c={PAPER}", f"fade=t=out:st={max(dur - 0.16, 0):.3f}:d=0.16:c={PAPER}", "format=yuv420p"]
    chain = ",".join(vf)
    if kind == "clip":  # a soft paper fade along the bottom, so captions read over the app
        labelled = len(chain) and chain
        head, tail = (labelled.split(",drawtext", 1) + [""])[:2] if label else (labelled.split(",trim=", 1)[0], "")
        rest = ("drawtext" + tail) if label else "trim=" + labelled.split(",trim=", 1)[1]
        graph = f"[0:v]{head}[a];movie={paper_fade()}[f];[a][f]overlay=0:0,{rest}[out]"
        run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-filter_complex", graph, "-map", "[out]", "-an",
             "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-r", str(FPS), out])
        return out
    clip = founder_clip(PIP[s["name"]]) if s["name"] in PIP else None
    if clip:
        at = next(line["start"] for line in s["lines"] if line["id"] == PIP[s["name"]])
        base, tail = chain.split(",trim=", 1)
        graph = (f"[0:v]{base}[a];[1:v]fps={FPS},crop=960:1080:330:0,scale={PIP_W}:{PIP_H},format=yuva420p[p0];movie={bubble_mask()},format=gray[m];"
                 f"[p0][m]alphamerge,fade=t=in:st=0:d=0.3:alpha=1,setpts=PTS-STARTPTS+{at:.3f}/TB[p];"
                 f"[a][p]overlay=W-{PIP_W}-70:150:eof_action=pass,trim={tail}[out]")
        run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-i", clip, "-filter_complex", graph, "-map", "[out]", "-an",
             "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-r", str(FPS), out])
        return out
    run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-vf", chain, "-an",
         "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-r", str(FPS), out])
    return out


# --- captions -----------------------------------------------------------------------------------------------------

FIX: list[tuple[str, str]] = []
ACCENT = re.compile(r"PartSmith|\\d|never|code|photo", re.I)


def ass_time(t: float) -> str:
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def phrases(words: list) -> list[list]:
    out, cur = [], []
    for w in words:
        cur.append(w)
        text = w[0]
        if len(cur) >= 6 or text.endswith((".", "?", ",", ":")) and len(cur) >= 2:
            out.append(cur)
            cur = []
    if cur:
        if out and len(cur) <= 2:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def norm_tok(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def aligned(caption: str, heard: list) -> list:
    """The caption's own words (real spelling) on Whisper's word times: matched words take their time, the rest are
    spread between their matched neighbours."""
    import difflib

    toks = caption.split()
    a = [norm_tok(t) for t in toks]
    b = [norm_tok(w) for w, *_ in heard]
    times: list = [None] * len(toks)
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            times[blk.a + k] = (heard[blk.b + k][1], heard[blk.b + k][2])
    first, last = heard[0][1], heard[-1][2]
    i = 0
    while i < len(toks):
        if times[i] is None:
            j = i
            while j < len(toks) and times[j] is None:
                j += 1
            lo = times[i - 1][1] if i > 0 else first
            hi = times[j][0] if j < len(toks) else last
            step = max(hi - lo, 0.05 * (j - i)) / (j - i)
            for k in range(i, j):
                times[k] = (lo + step * (k - i), lo + step * (k - i + 1))
            i = j
        else:
            i += 1
    return [[t, a0, a1] for t, (a0, a1) in zip(toks, times)]


def captions(tl: dict) -> tuple[str, str]:
    words = json.load(open(f"{WORK}/audio/words.json"))
    caps = {lid: caption for _s, lid, caption, *_ in load()}
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Atkinson Hyperlegible,56,&H00FFFFFF,&H00FFFFFF,&H66000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,120,120,118,1
Style: Ink,Atkinson Hyperlegible,56,&H0030221C,&H0030221C,&H10FFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,2,120,120,118,1
Style: Chip,Atkinson Hyperlegible,26,&H00E3EFF4,&H00FFFFFF,&H99000000,&H00000000,-1,0,0,0,100,100,2,0,1,2,0,9,60,60,44,1
Style: ChipInk,Atkinson Hyperlegible,26,&H00706156,&H00FFFFFF,&H20FFFFFF,&H00000000,-1,0,0,0,100,100,2,0,1,2,0,9,60,60,44,1
Style: ChipApp,Atkinson Hyperlegible,26,&H00706156,&H00FFFFFF,&H20FFFFFF,&H00000000,-1,0,0,0,100,100,2,0,1,2,0,9,60,60,104,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev, srt = [], []
    gold = r"{\c&H0F48D9&\fscx108\fscy108}"
    for s in tl["scenes"]:
        story = s["name"] in ("open", "close") or (s["name"] == "founder" and founder_clip("f1"))
        style = "Cap" if story else "Ink"
        plain = r"{\c&HFFFFFF&\fscx100\fscy100}" if story else r"{\c&H30221C&\fscx100\fscy100}"
        chip = "Chip" if story else ("ChipApp" if s["visual"][0] == "clip" else "ChipInk")
        if s["chapter"] and s["name"] not in ("title", "end", "hood"):
            ev.append(f"Dialogue: 1,{ass_time(s['start'] + 0.2)},{ass_time(s['start'] + s['dur'] - 0.1)},{chip},,0,0,0,,{s['chapter'].upper()}")
        if s["name"] in ("title", "recap"):
            continue
        for line in s["lines"]:
            base = s["start"] + line["start"]
            ws = aligned(caps[line["id"]], words[line["id"]])
            groups = phrases(ws)
            for gi, p in enumerate(groups):
                text = " ".join(w for w, *_ in p)
                for pat, rep in FIX:
                    text = re.sub(pat, rep, text)
                toks = text.split()
                if len(toks) != len(p):
                    toks = [w for w, *_ in p]
                srt.append((base + p[0][1], base + p[-1][2] + 0.25, " ".join(toks)))
                for i, (w, a, b) in enumerate(p):
                    a0 = base + a
                    # A phrase ends when the next one starts, so two never stack on screen.
                    next_start = groups[gi + 1][0][1] if gi + 1 < len(groups) else None
                    a1 = base + (p[i + 1][1] if i + 1 < len(p) else (min(b + 0.25, next_start) if next_start is not None else b + 0.25))
                    parts = []
                    for j, tok in enumerate(toks):
                        if j == i:
                            parts.append(gold + tok + plain)
                        elif ACCENT.search(tok) and j < i:
                            parts.append(tok)
                        else:
                            parts.append(tok)
                    ev.append(f"Dialogue: 0,{ass_time(a0)},{ass_time(a1)},{style},,0,0,0,,{' '.join(parts)}")
    ass = f"{BUILD}/captions.ass"
    open(ass, "w").write(head + "\n".join(ev) + "\n")
    srt_path = f"{FINAL}/PartSmith-film.srt"
    os.makedirs(FINAL, exist_ok=True)

    def st(t: float) -> str:
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(t * 1000) % 1000:03d}"

    open(srt_path, "w").write("\n".join(f"{i + 1}\n{st(a)} --> {st(b)}\n{t}\n" for i, (a, b, t) in enumerate(srt)))
    return ass, srt_path


# --- sound --------------------------------------------------------------------------------------------------------

def load_wav(path: str) -> np.ndarray:
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != SR:
        tmp = f"{BUILD}/rs.wav"
        run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ar", str(SR), tmp])
        a, _ = sf.read(tmp, dtype="float32", always_2d=True)
    if a.shape[1] == 1:
        a = np.repeat(a, 2, axis=1)
    return a


def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i < 0:
        clip, i = clip[-i:], 0
    n = min(len(clip), len(track) - i)
    if n > 0:
        track[i:i + n] += clip[:n] * gain


def sound(tl: dict) -> str:
    total = tl["total"]
    n = int(total * SR) + SR
    voice = np.zeros((n, 2), np.float32)
    for s in tl["scenes"]:
        for line in s["lines"]:
            place(voice, load_wav(f"{WORK}/audio/lines/{line['id']}.wav"), s["start"] + line["start"])
    peak = np.abs(voice).max()
    voice *= 0.5 / max(peak, 1e-6)
    sc = {s["name"]: s for s in tl["scenes"]}
    run([os.path.expanduser("~/Videos/debrief/.venv-music/bin/python"), f"{ROOT}/video/music.py"])
    music = load_wav(f"{WORK}/music/theme.wav")[:n]
    music = np.pad(music, ((0, n - len(music)), (0, 0)))
    # Duck the music under the voice: an envelope of the voice, 150 ms attack and 900 ms release, about 12 dB down.
    env = np.abs(voice[:, 0])
    hop = SR // 100
    frames = env[: len(env) // hop * hop].reshape(-1, hop).max(axis=1)
    active = (frames > 0.02).astype(np.float32)
    g = np.zeros_like(active)
    level = 0.0
    for i, a in enumerate(active):
        level += (a - level) * (1 - np.exp(-1 / (15 if a > level else 90)))
        g[i] = level
    duck = np.repeat(1 - 0.75 * g, hop)
    duck = np.pad(duck, (0, n - len(duck)), constant_values=duck[-1])
    mpeak = np.abs(music).max()
    music = music / max(mpeak, 1e-6) * 0.42 * duck[:, None]
    # Fade the music in over 2 s and out over the last 3 s.
    fade = np.ones(n, np.float32)
    fade[: 2 * SR] = np.linspace(0, 1, 2 * SR)
    end_i = int(total * SR)
    fade[end_i - 3 * SR:end_i] = np.linspace(1, 0, 3 * SR)
    fade[end_i:] = 0
    music *= fade[:, None]
    fx = np.zeros_like(voice)
    S = f"{WORK}/sfx"
    names = ("whoosh", "hit", "riser", "click", "shutter", "ui-click", "ui-tick", "ui-select", "ui-confirm", "ui-error", "ui-pop", "ui-glass", "ui-drop")
    fxs = {k: load_wav(f"{S}/{k}.wav") for k in names}
    whoosh, hit, riser = fxs["whoosh"], fxs["hit"], fxs["riser"]
    words = json.load(open(f"{WORK}/audio/words.json"))

    def spoken(scene: str, lid: str, pat: str, fallback: float = 0.0) -> float:
        """The film time a word lands (Whisper's time), so a sound hits exactly on the spoken word."""
        s0 = sc[scene]
        line = next(x for x in s0["lines"] if x["id"] == lid)
        for w, a0, _a1 in words[lid]:
            if re.search(pat, w, re.I):
                return s0["start"] + line["start"] + a0
        return s0["start"] + line["start"] + fallback

    def line_at(scene: str, lid: str) -> float:
        s0 = sc[scene]
        return s0["start"] + next(x for x in s0["lines"] if x["id"] == lid)["start"]

    def play(name: str, at: float, gain: float) -> None:
        place(fx, fxs[name], at, gain)

    for s in tl["scenes"][1:]:
        place(fx, whoosh, s["start"] - 0.3, 0.16)
    place(fx, hit, sc["title"]["start"], 0.5)
    # the story
    play("ui-drop", spoken("open", "n03", r"snapped"), 0.5)
    play("hit", spoken("open", "n07", r"billion|62"), 0.3)
    # the flow: one tick on each step as it lights up
    for lid, pat in (("w2", r"photo"), ("w2", r"measured"), ("w2", r"program"), ("w3", r"check"), ("w3", r"fix"), ("w4", r"review"), ("w4", r"file")):
        play("ui-select", spoken("flow", lid, pat), 0.6)
    play("ui-confirm", spoken("flow", "w4", r"file") + 0.5, 0.5)
    # the camera, the scan, the sizes
    play("shutter", spoken("photo", "n11", r"photo"), 0.8)
    for lid in ("v2", "v3", "v4"):
        place(fx, whoosh, line_at("see", lid) - 0.1, 0.12)
        play("ui-tick", line_at("see", lid), 0.6)
    # fail, fix, pass
    play("ui-error", spoken("loop", "n14", r"failed", 3.0), 0.75)
    play("ui-select", line_at("loop", "n15"), 0.5)
    play("ui-confirm", spoken("loop", "n16", r"verified", 2.0), 0.8)
    play("hit", spoken("loop", "n16", r"verified", 2.0), 0.3)
    play("ui-pop", sc["export"]["start"] + 1.2, 0.5)
    # the lie
    play("ui-error", spoken("lie", "n19", r"blocked", 3.5), 0.8)
    play("hit", line_at("lie", "n20"), 0.3)
    # the knob and the voice
    for k in range(4):
        play("ui-tick", sc["knobs"]["start"] + 0.5 + k * 0.3, 0.45)
    play("ui-confirm", line_at("say", "s2") + 2.0, 0.6)
    # the comparison, then the proof
    for lid, pat in (("c2", r"guess"), ("c3", r"scans"), ("c3", r"text"), ("c3", r"numbers")):
        play("ui-select", spoken("others", lid, pat), 0.45)
    play("ui-confirm", spoken("others", "c4", r"check", 1.0), 0.6)
    play("hit", spoken("before", "b2", r"move", 2.0), 0.28)
    play("ui-confirm", spoken("before", "b2", r"knob", 3.0), 0.5)
    for pat in (r"caliper", r"cad", r"trial"):
        play("ui-select", spoken("saves", "e4", pat), 0.6)
    for k in range(6):
        play("ui-tick", sc["meta"]["start"] + 0.1 + k * 0.12, 0.35)
    for line in sc["test"]["lines"]:
        play("ui-pop", sc["test"]["start"] + line["start"] + 0.2, 0.32)
    play("hit", line_at("market", "k1") + 0.3, 0.25)
    play("hit", line_at("market", "k2") + 0.3, 0.2)
    # the lift into the vision, then the close
    vis = sc["vision"]
    place(fx, riser, vis["start"] - riser.shape[0] / SR, 0.3)
    place(fx, hit, vis["start"], 0.3)
    place(fx, hit, sc["end"]["start"], 0.45)
    mix = voice + music + fx
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    out = f"{BUILD}/mix.wav"
    sf.write(out, mix, SR)
    sf.write(f"{BUILD}/voice.wav", voice, SR)
    sf.write(f"{BUILD}/music.wav", music, SR)
    return out


def film() -> None:
    tl = json.load(open(f"{BUILD}/timeline.json"))
    parts = [render_scene(s) for s in tl["scenes"]]
    with open(f"{BUILD}/concat.txt", "w") as f:
        f.writelines(f"file '{p}'\n" for p in parts)
    run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{BUILD}/concat.txt", "-c", "copy",
         f"{BUILD}/picture.mp4"])
    ass, srt = captions(tl)
    mix = sound(tl)
    os.makedirs(FINAL, exist_ok=True)
    out = f"{FINAL}/PartSmith-film.mp4"
    clean = f"{FINAL}/PartSmith-film-nocaptions.mp4"
    common = ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-tune", "film", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", str(tl["total"])]
    af = "loudnorm=I=-14.5:TP=-2:LRA=11,alimiter=limit=0.75:level=false"
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", f"{BUILD}/picture.mp4", "-i", mix, "-map", "0:v", "-map", "1:a",
         "-vf", f"ass={ass}:fontsdir={FONTS}", "-af", af, *common, out])
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", f"{BUILD}/picture.mp4", "-i", mix, "-map", "0:v", "-map", "1:a",
         "-af", af, *common, clean])
    run(["ffmpeg", "-loglevel", "error", "-y", "-i", out, "-vf", "scale=1280:720", "-c:v", "libx264", "-crf", "26",
         "-preset", "medium", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", f"{FINAL}/PartSmith-film-720p.mp4"])
    chapters = []
    for s in tl["scenes"]:
        if s["chapter"] and (not chapters or chapters[-1][1] != s["chapter"]):
            chapters.append((s["start"], s["chapter"]))
    merged = []
    for i, (t, name) in enumerate(chapters):
        nxt = chapters[i + 1][0] if i + 1 < len(chapters) else tl["total"]
        if merged and (nxt - t < 10 or t - merged[-1][0] < 10) and nxt - t < 10:
            continue
        merged.append((t, name))
    text = "\n".join(f"{int(t // 60)}:{int(t % 60):02d} {name}" for t, name in merged)
    open(f"{FINAL}/chapters.txt", "w").write(("0:00 " + merged[0][1] + "\n" + "\n".join(text.splitlines()[1:])) + "\n")
    print("wrote", out, "length", tl["total"], "s")


def storyboard() -> None:
    """video/storyboard.md: one row per scene, from the scene list and the real timeline."""
    tl = json.load(open(f"{BUILD}/timeline.json"))
    caps = {lid: caption for _s, lid, caption, *_ in load()}
    rows = ["# Film storyboard", "", "Generated by `video/build.py storyboard` from the scene list and the voice lengths; numbers come from `video/facts.py`.", "",
            f"Length: {tl['total']:.1f} s.", "", "| Time | Scene | Narration | On screen | Motion | Label on screen |", "|---|---|---|---|---|---|"]
    for s in tl["scenes"]:
        v = s["visual"]
        screen = {"gfx": "drawn scene (`three.html`)" if v[1:] == ["three"] else "drawn scene (`graphics.html`)", "face": "founder on camera, or a card until the clip exists"}.get(v[0], f"real app, flow `{v[1]}`" if len(v) > 1 else "")
        push = v[4]["push"] if len(v) > 4 else None
        motion = f"push to {push[2]}× at ({push[3]}, {push[4]})" if push else ("slow drift" if v[0] == "clip" else "scene's own")
        said = " ".join(caps[l["id"]] for l in s["lines"]).replace("|", "/")
        rows.append(f"| {int(s['start'] // 60)}:{s['start'] % 60:04.1f} | {s['name']} | {said} | {screen} | {motion} | {LABELS.get(s['name'], '').replace('{speed}', str(v[3]) if len(v) > 3 else '')} |")
    open(f"{ROOT}/video/storyboard.md", "w").write("\n".join(rows) + "\n")
    print("wrote video/storyboard.md")


def check() -> None:
    """Scripted checks on the final film: stream lengths, loudness, voice gaps, and what Whisper hears against the script."""
    import difflib

    from faster_whisper import WhisperModel

    film_path = f"{FINAL}/PartSmith-film.mp4"
    tl = json.load(open(f"{BUILD}/timeline.json"))
    for stream in ("v:0", "a:0"):
        got = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration", "-of", "csv=p=0", film_path], capture_output=True, text=True).stdout.strip()
        print(f"stream {stream}: {got} s (timeline {tl['total']})")
    print("length:", f"{int(tl['total'] // 60)}:{tl['total'] % 60:04.1f}")
    loud = subprocess.run(["ffmpeg", "-hide_banner", "-i", film_path, "-af", "loudnorm=print_format=summary", "-f", "null", "-"], capture_output=True, text=True).stderr
    print("\n".join(x for x in loud.splitlines() if re.match(r"Input (Integrated|True Peak)", x)))
    voice, _ = sf.read(f"{BUILD}/voice.wav", dtype="float32", always_2d=True)
    hop = SR // 10
    env = np.abs(voice[:, 0])[: len(voice) // hop * hop].reshape(-1, hop).max(axis=1) > 0.01
    gap, gaps = 0, []
    for i, on in enumerate(env):
        if on:
            if gap > 25:
                gaps.append((round((i - gap) / 10, 1), gap / 10))
            gap = 0
        else:
            gap += 1
    print("voice gaps over 2.5 s (start, length):", gaps)
    last = 0.0
    longest = 0.0
    for s in tl["scenes"]:
        longest = max(longest, s["dur"])
    print("longest scene:", round(longest, 1), "s")
    first_product = next(s["start"] for s in tl["scenes"] if s["visual"][0] == "clip")
    print("real product first on screen at:", round(first_product, 1), "s")
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(film_path, beam_size=5, language="en")
    heard = " ".join(x.text for x in segs).lower()
    said = " ".join(sp for *_x, sp, _e, _c in load()).lower()
    clean = lambda t: re.sub(r"[^a-z0-9 ]", " ", t).split()  # noqa: E731
    print("word match against the script:", round(difflib.SequenceMatcher(None, clean(said), clean(heard)).ratio(), 3))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "timeline":
        timeline()
    elif cmd == "stills":
        stills()
    elif cmd == "gfx":
        gfx(set(sys.argv[2:]))
    elif cmd == "film":
        film()
    elif cmd == "storyboard":
        storyboard()
    elif cmd == "check":
        check()
