"""Generated shots cases: synthetic shots spliced at known frames, so every transition's truth is exact. #1208.

Sources are ffmpeg lavfi generators only, each with a seeded pan; no film frame
is used. Joins are hard cuts and xfade dissolves and fades to black, allocated
exactly across the set; flashes and whip pans are planted inside shots.
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from evals.importers import Imported, provenance

LANE = "shots"
VERSION = "1"
SEED = 1208
SOURCE = f"generated:evals.importers.shots_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated shot-boundary clips"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/shots_synth.py"
LICENSE = "generated"
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
PROMPT = "Mark every shot boundary in this clip: hard cuts, dissolves and fades."

FPS = 24
WIDTH, HEIGHT = 192, 108
#: x264 constant rate factor of the committed clips.
CRF = 30
CLIPS = 10
JOINS_PER_CLIP = 15
CUT_SHARE = 0.4
GRADUAL_FRAMES = (6, 12, 24)
#: A shot's own frames are drawn from this range, raised where its transitions need more.
SHOT_FRAMES = (36, 96)
#: Frames of a shot outside both of its transitions.
CLEAN_FRAMES = 12
FLASH_SHARE = 0.15
WHIP_SHARE = 0.1
WHIP_FRAMES = 6
SOURCES = ("gradients", "mandelbrot", "testsrc2", "life", "cellauto", "sierpinski", "noise")
XFADE = {"dissolve": "fade", "fade": "fadeblack"}
#: Largest committed clip; the whole set stays under twelve of these.
MAX_CLIP_BYTES = 500_000


def segment(source: str, frames: int, seed: int) -> dict:
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; known: {', '.join(SOURCES)}")
    return {"source": source, "seed": seed, "frames": frames}


def _plant(rng: random.Random, seg: dict, head: int, tail: int) -> dict:
    """seg with a flash or a whip pan inside its clean frames, when drawn and when there is room."""
    lo, hi = head + CLEAN_FRAMES // 2, seg["frames"] - tail - CLEAN_FRAMES // 2
    if rng.random() < FLASH_SHARE and hi - lo > 2:
        a = rng.randrange(lo, hi - 2)
        seg = {**seg, "flash": [[a, a + rng.randrange(2)]]}
    elif rng.random() < WHIP_SHARE and hi - lo > WHIP_FRAMES:
        a = rng.randrange(lo, hi - WHIP_FRAMES)
        seg = {**seg, "whip": [[a, a + WHIP_FRAMES - 1]]}
    return seg


def _shots(rng: random.Random, joins: list[dict], low: int, high: int, plant: bool) -> list[dict]:
    pads = [0, *(j["frames"] for j in joins), 0]
    out, last = [], ""
    for i in range(len(joins) + 1):
        need = pads[i] + pads[i + 1] + CLEAN_FRAMES
        source = rng.choice([s for s in SOURCES if s != last])
        seg = segment(source, rng.randint(max(low, need), max(high, need)), rng.randrange(1 << 30))
        out.append(_plant(rng, seg, pads[i], pads[i + 1]) if plant else seg)
        last = source
    return out


def _spec(segments: list[dict], joins: list[dict]) -> dict:
    return {"fps": FPS, "width": WIDTH, "height": HEIGHT, "segments": segments, "joins": joins}


def control_spec(name: str, seed: int = SEED, shots: int = 24) -> dict:
    """The all-cut control (short shots, hard cuts only) or the no-cut one (one shot with flashes and whips)."""
    rng = random.Random(f"shots-control:{VERSION}:{seed}:{name}")
    if name == "all-cut":
        joins = [{"kind": "cut", "frames": 0}] * (shots - 1)
        return _spec(_shots(rng, joins, 12, 30, plant=False), joins)
    if name == "no-cut":
        seg = segment("mandelbrot", 720, rng.randrange(1 << 30))
        return _spec([{**seg, "flash": [[120, 121], [480, 480]], "whip": [[300, 300 + WHIP_FRAMES - 1]]}], [])
    raise ValueError(f"unknown control {name!r}; known: all-cut, no-cut")


def fetch(seed: int = SEED) -> list[dict]:
    """The exam clips, joins allocated exactly and dealt out in a seeded order, then the two controls."""
    rng = random.Random(f"shots-synth:{VERSION}:{seed}")
    total = CLIPS * JOINS_PER_CLIP
    cuts = round(total * CUT_SHARE)
    kinds = [(k, n) for k in ("dissolve", "fade") for n in GRADUAL_FRAMES]
    if (total - cuts) % len(kinds):
        raise ValueError(f"{total - cuts} gradual joins do not split evenly over {len(kinds)} kinds")
    pool = [("cut", 0)] * cuts + kinds * ((total - cuts) // len(kinds))
    rng.shuffle(pool)
    rows = []
    for i in range(CLIPS):
        joins = [{"kind": k, "frames": n} for k, n in pool[i * JOINS_PER_CLIP:(i + 1) * JOINS_PER_CLIP]]
        rows.append({"item": i, "seed": seed, "role": "exam", "name": f"shots-synth-{i:02d}",
                     "spec": _spec(_shots(rng, joins, *SHOT_FRAMES, plant=True), joins)})
    for j, name in enumerate(("all-cut", "no-cut")):
        rows.append({"item": CLIPS + j, "seed": seed, "role": "control", "name": f"shots-control-{name}",
                     "spec": control_spec(name, seed)})
    return rows


def truth(spec: dict) -> dict:
    """Transitions and planted negatives in output frames; a cut is the first frame of the new shot."""
    transitions, negatives, pos = [], [], 0
    segments, joins = spec["segments"], spec["joins"]
    for i, seg in enumerate(segments):
        for kind in ("flash", "whip"):
            for a, b in seg.get(kind) or ():
                negatives.append({"kind": kind, "first": pos + a, "last": pos + b})
        negatives.sort(key=lambda n: n["first"])
        if i == len(joins):
            pos += seg["frames"]
            break
        join = joins[i]
        pos += seg["frames"] - join["frames"]
        last = pos if join["kind"] == "cut" else pos + join["frames"] - 1
        transitions.append({"kind": join["kind"], "first": pos, "last": last})
    return {"fps": spec["fps"], "frames": pos, "transitions": transitions, "negatives": negatives}


def _hex(rng: random.Random) -> str:
    return "0x%06x" % rng.randrange(1 << 24)


def _source(seg: dict, w: int, h: int, fps: int) -> str:
    """The lavfi graph of one shot's source, on a canvas three widths by two heights."""
    rng = random.Random(seg["seed"])
    sw, sh, kind = 3 * w, 2 * h, seg["source"]
    if kind == "gradients":
        return (f"gradients=s={sw}x{sh}:r={fps}:c0={_hex(rng)}:c1={_hex(rng)}:c2={_hex(rng)}:nb_colors=3"
                f":speed={rng.uniform(0.01, 0.04):.3f}:seed={rng.randrange(1 << 30)}")
    if kind == "mandelbrot":
        return (f"mandelbrot=s={sw}x{sh}:r={fps}:start_x={rng.uniform(-1.5, 0.3):.4f}"
                f":start_y={rng.uniform(-0.8, 0.8):.4f}:start_scale={rng.uniform(0.5, 3.0):.3f}")
    if kind == "testsrc2":
        return f"testsrc2=s={sw}x{sh}:r={fps},hue=h={rng.randrange(360)}"
    if kind == "life":
        return (f"life=s={sw // 4}x{sh // 4}:r={fps}:seed={rng.randrange(1 << 30)}:ratio={rng.uniform(0.2, 0.6):.2f}"
                f":mold=10:life_color={_hex(rng)}:death_color={_hex(rng)},scale={sw}:{sh}:flags=neighbor")
    if kind == "cellauto":
        return (f"cellauto=s={sw // 2}x{sh // 2}:r={fps}:rule={rng.choice((18, 30, 90, 110, 150))}"
                f":seed={rng.randrange(1 << 30)}:scroll=1,scale={sw}:{sh}:flags=neighbor,format=rgb24"
                f",lutrgb=r=val*{rng.uniform(0.3, 1):.2f}:g=val*{rng.uniform(0.3, 1):.2f}:b=val*{rng.uniform(0.3, 1):.2f}")
    if kind == "sierpinski":
        return (f"sierpinski=s={sw}x{sh}:r={fps}:seed={rng.randrange(1 << 30)}:jump={rng.randrange(1, 5)}"
                f":type={rng.choice(('carpet', 'triangle'))}")
    if kind == "noise":
        return f"color=c={_hex(rng)}:s={sw}x{sh}:r={fps},noise=alls={rng.randrange(10, 40)}:allf=t,boxblur=6"
    raise ValueError(f"unknown source {kind!r}; known: {', '.join(SOURCES)}")


def _crop(seg: dict, w: int, h: int) -> str:
    """A slow seeded pan over the canvas, plus a whip of one width where the segment plants one."""
    rng = random.Random(seg["seed"] ^ 0x5EED)
    n = max(1, seg["frames"])
    x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
    dx, dy = rng.uniform(-1, 1) * w / n, rng.uniform(-1, 1) * h / n
    x = f"clip({x0:.1f}+{dx:.4f}*n\\,0\\,{w})"
    for k, (a, b) in enumerate(seg.get("whip") or ()):
        x += f"{'+' if k % 2 == 0 else '-'}{w}*clip((n-{a})/{b - a + 1}\\,0\\,1)"
    y = f"clip({y0:.1f}+{dy:.4f}*n\\,0\\,{h})"
    return f"crop={w}:{h}:x='{x}':y='{y}'"


def _chain(i: int, seg: dict, spec: dict) -> str:
    w, h, fps = spec["width"], spec["height"], spec["fps"]
    chain = [f"trim=end_frame={seg['frames']}", "setpts=PTS-STARTPTS", _crop(seg, w, h), "setsar=1",
             "format=yuv420p", f"fps={fps}", f"settb=1/{fps}"]
    for a, b in seg.get("flash") or ():
        chain.append(f"lutyuv=y=235:enable='between(n\\,{a}\\,{b})'")
    return f"[{i}:v]{','.join(chain)}[s{i}]"


def build(spec: dict, out: Path) -> dict:
    """Render `spec` to an H.264 clip at `out`; returns its truth."""
    args, graph = [], []
    for i, seg in enumerate(spec["segments"]):
        args += ["-f", "lavfi", "-i", _source(seg, spec["width"], spec["height"], spec["fps"])]
        graph.append(_chain(i, seg, spec))
    fps, cur, length = spec["fps"], "s0", spec["segments"][0]["frames"]
    for i, join in enumerate(spec["joins"], start=1):
        label = f"j{i}"
        if join["kind"] == "cut":
            # concat leaves a microsecond timebase that xfade refuses (KB RULE #1055).
            graph.append(f"[{cur}][s{i}]concat=n=2:v=1:a=0,settb=1/{fps},fps={fps}[{label}]")
        elif join["kind"] in XFADE:
            offset = (length - join["frames"]) / fps
            graph.append(f"[{cur}][s{i}]xfade=transition={XFADE[join['kind']]}:duration={join['frames'] / fps}"
                         f":offset={offset}[{label}]")
        else:
            raise ValueError(f"unknown join kind {join['kind']!r}; known: cut, {', '.join(XFADE)}")
        length += spec["segments"][i]["frames"] - join["frames"]
        cur = label
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args,
           "-filter_complex", ";".join(graph), "-map", f"[{cur}]", "-an", "-c:v", "libx264", "-preset", "medium",
           "-crf", str(CRF), "-pix_fmt", "yuv420p", "-map_metadata", "-1", "-fflags", "+bitexact",
           "-flags:v", "+bitexact", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return truth(spec)


def case_of(row: dict) -> dict:
    """The case file for a row, without rendering its clip."""
    case_id = row["name"]
    att = provenance(sys.modules[__name__], row["item"],
                     f"lavfi sources with a seeded pan, {row['role']} clip, x264 crf {CRF}, "
                     f"{row['spec']['width']}x{row['spec']['height']} at {row['spec']['fps']} fps")
    att.update(version=VERSION, seed=row["seed"], role=row["role"], spec=row["spec"])
    t = truth(row["spec"])
    return {"id": case_id, "modality": LANE, "prompt": PROMPT, "input_file": f"clips/{case_id}.mp4",
            "assert": {"fps": t["fps"], "frames": t["frames"], "transitions": t["transitions"],
                       "negatives": t["negatives"]},
            "attribution": att}


def convert(row: dict) -> Imported:
    case = case_of(row)
    with tempfile.TemporaryDirectory() as d:
        clip = Path(d) / "clip.mp4"
        build(row["spec"], clip)
        data = clip.read_bytes()
    return Imported(case, files=((case["input_file"], data),))


def _record(transitions: list[dict]) -> str:
    return json.dumps({"transitions": transitions})


def _reference(case) -> str:
    return _record([{"at": t["first"] if t["kind"] == "cut" else (t["first"] + t["last"]) // 2,
                     "kind": "cut" if t["kind"] == "cut" else "gradual"}
                    for t in case.assertions["transitions"]])


#: The negative control: the truth passes every case, nothing passes only the no-cut clip, every frame none.
RESPONDERS = {
    "reference": _reference,
    "nothing": lambda case: _record([]),
    "every-frame": lambda case: _record([{"at": i, "kind": "cut"} for i in range(case.assertions["frames"])]),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
