"""Generated svg cases: a seeded scene becomes the prompt, a structure assertion and a reference drawing. #1050.

Every property is read from the markup by harness/checks/svg.structure, never by
a judge. Strata: easy asks for one or two properties, medium three, hard four or more.
"""
from __future__ import annotations

import hashlib
import math
import random
import sys

from evals.importers import Imported, provenance

LANE = "svg"
VERSION = "1"
SEED = 1050
COUNT = 640
SOURCE = f"generated:evals.importers.svg_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated svg cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/svg_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "svg-synth"
#: Redraws of one row before a kind is called too small to fill its share.
ATTEMPTS = 50
XMLNS = "http://www.w3.org/2000/svg"

#: Hex colours with no CSS name and no near-white, so a mark is ink and has one spelling.
PALETTE = ("#e63946", "#457b9d", "#2a9d8f", "#f4a261", "#6a4c93", "#1d3557", "#8ab17d",
           "#e76f51", "#264653", "#b5838d")
VIEWBOXES = ((0, 0, 200, 200), (0, 0, 240, 120), (0, 0, 320, 160), (0, 0, 100, 100),
             (0, 0, 300, 200), (0, 0, 400, 300))
WORDS = ("alpha", "bravo", "cedar", "delta", "ember", "fjord", "garnet", "harbor", "indigo",
         "juniper", "kelp", "lumen", "maple", "nova", "onyx", "pike", "quartz", "rook")
NOTHING_ELSE = "Draw nothing else: no background, border, axis or other extra shapes."
NO_TRANSFORM = "Do not use transform attributes."
FILLS = "Set every colour with a fill attribute."


def _vb(box) -> str:
    return " ".join(map(str, box))


def _svg(box, body: list[str]) -> str:
    return f'<svg xmlns="{XMLNS}" viewBox="{_vb(box)}">\n' + "\n".join(
        "  " + line for line in body) + "\n</svg>\n"


def _slots(box, n: int):
    """n left-to-right cells across the box: (centre x, cell width)."""
    w = box[2] / n
    return [(box[0] + w * (i + 0.5), w) for i in range(n)]


def _dots(rng, box):
    n, fill = rng.randint(4, 12), rng.choice(PALETTE)
    cy, body = box[1] + box[3] / 2, []
    for cx, w in _slots(box, n):
        body.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{min(w, box[3]) * 0.35:g}" fill="{fill}"/>')
    prompt = (f"Draw exactly {n} circles, all filled {fill}, on a viewBox of \"{_vb(box)}\". "
              f"{FILLS} {NOTHING_ELSE}")
    return "easy", prompt, {"viewbox": list(box), "count": {"circle": n}, "fill": {"circle": fill},
            "inside": True}, body, True


def _blobs(rng, box):
    n = rng.randint(3, 9)
    a = rng.randint(1, n - 1)
    fa, fb = rng.sample(PALETTE, 2)
    cy, body = box[1] + box[3] / 2, []
    for i, (cx, w) in enumerate(_slots(box, n)):
        r = min(w, box[3]) * 0.3
        body.append(f'<path d="M{cx - r:g},{cy + r:g} L{cx:g},{cy - r:g} L{cx + r:g},{cy + r:g} Z" '
                    f'fill="{fa if i < a else fb}"/>')
    prompt = (f"Draw exactly {n} separate filled shapes of any kind: {a} filled {fa} and "
              f"{n - a} filled {fb}. {FILLS} {NOTHING_ELSE}")
    return "easy", prompt, {"marks": n, "tally": {fa: a, fb: n - a}}, body, False


def _row(rng, box):
    n = rng.randint(4, 9)
    fills = [rng.choice(PALETTE) for _ in range(n)]
    body = []
    for (cx, w), f in zip(_slots(box, n), fills):
        s = min(w, box[3]) * 0.7
        body.append(f'<rect x="{cx - s / 2:g}" y="{box[1] + (box[3] - s) / 2:g}" width="{s:g}" '
                    f'height="{s:g}" fill="{f}"/>')
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw a row of exactly {n} squares as <rect> "
              f"elements, coloured from left to right: {', '.join(fills)}. {FILLS} "
              f"{NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"rect": n},
            "order": {"tag": "rect", "axis": "x", "fills": fills}, "inside": True}
    return "medium", prompt, spec, body, True


def _mix(rng, box):
    a, b, c = rng.randint(1, 5), rng.randint(1, 5), rng.randint(1, 5)
    fa, fb, fc = rng.sample(PALETTE, 3)
    body, slots = [], _slots(box, a + b + c)
    cy = box[1] + box[3] / 2
    kinds = ["circle"] * a + ["rect"] * b + ["ellipse"] * c
    rng.shuffle(kinds)
    for kind, (cx, w) in zip(kinds, slots):
        s = min(w, box[3]) * 0.35
        if kind == "circle":
            body.append(f'<circle cx="{cx:g}" cy="{cy:g}" r="{s:g}" fill="{fa}"/>')
        elif kind == "rect":
            body.append(f'<rect x="{cx - s:g}" y="{cy - s:g}" width="{2 * s:g}" height="{2 * s:g}" '
                        f'fill="{fb}"/>')
        else:
            body.append(f'<ellipse cx="{cx:g}" cy="{cy:g}" rx="{s:g}" ry="{s / 2:g}" fill="{fc}"/>')
    prompt = (f"Draw exactly {a} <circle> filled {fa}, exactly {b} <rect> filled {fb} and "
              f"exactly {c} <ellipse> filled {fc}, none of them overlapping. {FILLS} {NOTHING_ELSE}")
    spec = {"count": {"circle": a, "rect": b, "ellipse": c},
            "fill": {"circle": fa, "rect": fb, "ellipse": fc}}
    return "medium", prompt, spec, body, True


def _closed(rng, box):
    n, fill = rng.randint(3, 8), rng.choice(PALETTE)
    sides = rng.choice((3, 4, 5, 6))
    noun = {3: "triangle", 4: "quadrilateral", 5: "pentagon", 6: "hexagon"}[sides]
    cy, body = box[1] + box[3] / 2, []
    for cx, w in _slots(box, n):
        r = min(w, box[3]) * 0.35
        pts = [(cx + r * math.cos(2 * math.pi * k / sides - math.pi / 2),
                cy + r * math.sin(2 * math.pi * k / sides - math.pi / 2)) for k in range(sides)]
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z"
        body.append(f'<path d="{d}" fill="{fill}"/>')
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw exactly {n} {noun}s, each a single closed "
              f"<path> whose d ends with Z, filled {fill}. Use no other element type. {FILLS} "
              f"{NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"path": n}, "closed": n, "fill": {"path": fill}}
    return "medium", prompt, spec, body, True


def _badge(rng, box):
    n = rng.randint(2, 4)
    words = rng.sample(WORDS, n - 1) + [
        f"v{rng.randint(1, 9)}.{rng.randint(0, 19)}.{rng.randint(0, 99)}"]
    fills = rng.sample(PALETTE, n)
    h, part = box[3] * 0.5, box[2] / n
    y = box[1] + box[3] * 0.25
    body = []
    for i, (word, f) in enumerate(zip(words, fills)):
        x = box[0] + i * part
        body.append(f'<rect x="{x:g}" y="{y:g}" width="{part:g}" height="{h:g}" fill="{f}"/>')
        body.append(f'<text x="{x + part / 2:g}" y="{y + h * 0.65:g}" font-size="{h * 0.3:g}" '
                    f'text-anchor="middle" fill="#1d3557">{word}</text>')
    parts = "; ".join(f"a <rect> filled {f} reading \"{w}\"" for w, f in zip(words, fills))
    prompt = (f"Draw a {n}-part badge on a viewBox of \"{_vb(box)}\", its parts side by side "
              f"from left to right: {parts}. Each word is in its own <text> element. Exactly "
              f"{n} <rect> and {n} <text>, and no other text. {FILLS} {NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"rect": n, "text": n},
            "order": {"tag": "rect", "axis": "x", "fills": fills}, "labels": words, "inside": True}
    return "hard", prompt, spec, body, True


def _bars(rng, box):
    n = rng.randint(4, 10)
    values = [rng.randint(1, 40) for _ in range(n)]
    fill = rng.choice(PALETTE)
    unit = rng.choice((0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6))
    while unit * max(values) > box[3] * 0.8:
        unit /= 2
    base = box[1] + box[3] - rng.randint(5, 20)
    body = []
    for (cx, w), v in zip(_slots(box, n), values):
        bw = w * 0.6
        body.append(f'<rect x="{cx - bw / 2:g}" y="{base - v * unit:g}" width="{bw:g}" '
                    f'height="{v * unit:g}" fill="{fill}"/>')
        body.append(f'<text x="{cx:g}" y="{base - v * unit - 2:g}" font-size="{w * 0.3:g}" '
                    f'text-anchor="middle">{v}</text>')
    prompt = (f"Draw a bar chart on a viewBox of \"{_vb(box)}\" with exactly {n} bars, left to "
              f"right, of values {', '.join(map(str, values))}. Each bar is one <rect> filled "
              f"{fill}, {unit:g} user units tall per unit of value, all bars standing on the line "
              f"y={base:g}. Label each bar with its value in a <text> element and add no other "
              f"text. Use no other <rect>. {FILLS} {NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"rect": n, "text": n}, "fill": {"rect": fill},
            "heights": {"values": values, "unit": unit, "base": base},
            "labels": [str(v) for v in values], "inside": True}
    return "hard", prompt, spec, body, True


def _centre(rng, box):
    """A centre and a radius that fit the box with room to spare."""
    r = rng.randint(int(min(box[2], box[3]) * 0.2), int(min(box[2], box[3]) * 0.35))
    cx = rng.randint(int(box[0] + r + 8), int(box[0] + box[2] - r - 8))
    cy = rng.randint(int(box[1] + r + 8), int(box[1] + box[3] - r - 8))
    return cx, cy, r


def _ring(rng, box):
    n, fill = rng.randint(5, 12), rng.choice(PALETTE)
    cx, cy, r = _centre(rng, box)
    dot = max(1, round(r * 0.12))
    body = []
    for k in range(n):
        t = 2 * math.pi * k / n
        body.append(f'<circle cx="{cx + r * math.sin(t):.2f}" cy="{cy - r * math.cos(t):.2f}" '
                    f'r="{dot}" fill="{fill}"/>')
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw exactly {n} dots as <circle> elements of "
              f"radius {dot}, filled {fill}, evenly spaced around a ring of radius {r} centred at "
              f"({cx}, {cy}): the first dot straight above the centre, the rest following "
              f"clockwise. Give each centre to two decimal places. {FILLS} {NO_TRANSFORM} "
              f"{NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"circle": n}, "fill": {"circle": fill},
            "ring": {"cx": cx, "cy": cy, "r": r, "n": n}, "inside": True}
    return "hard", prompt, spec, body, True


def _clock(rng, box):
    h, m = rng.randint(1, 12), rng.randrange(0, 60, 5)
    cx, cy, r = _centre(rng, box)
    hour, minute = (h % 12) * 30 + m * 0.5, m * 6.0
    ends = []
    for deg, length in ((hour, r * 0.5), (minute, r * 0.85)):
        t = math.radians(deg)
        ends.append((cx + length * math.sin(t), cy - length * math.cos(t)))
    body = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1d3557" stroke-width="2"/>']
    for (x, y), width in zip(ends, (4, 2)):
        body.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.2f}" y2="{y:.2f}" stroke="#1d3557" '
                    f'stroke-width="{width}"/>')
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw an analogue clock face showing "
              f"{h}:{m:02d}: one <circle> of radius {r} centred at ({cx}, {cy}) for the face, and "
              f"two <line> elements for the hands, each starting exactly at the centre. The hour "
              f"hand is shorter than the minute hand and sits where it really is at {h}:{m:02d}. "
              f"No numbers, ticks or other marks. {NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"circle": 1, "line": 2},
            "hands": {"cx": cx, "cy": cy, "hour": hour, "minute": minute}, "inside": True}
    return "hard", prompt, spec, body, True


def _concentric(rng, box):
    n = rng.randint(3, 6)
    cx, cy, r = _centre(rng, box)
    radii = sorted(rng.sample(range(4, r + 1), n), reverse=True)
    fills = rng.sample(PALETTE, n)
    body = [f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="{f}"/>' for rr, f in zip(radii, fills)]
    told = list(zip(radii, fills))
    rng.shuffle(told)
    listed = "; ".join(f"radius {rr} filled {f}" for rr, f in told)
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw {n} concentric filled circles centred at "
              f"({cx}, {cy}): {listed}. Every circle must stay visible as a ring or disc, so "
              f"order them so that no circle hides another. {FILLS} {NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"circle": n},
            "stack": {"cx": cx, "cy": cy, "radii": radii, "fills": fills}, "inside": True}
    return "hard", prompt, spec, body, True


def _groups(rng, box):
    tags = ("circle", "rect", "ellipse")
    ids = rng.sample(WORDS, 3)
    counts = [rng.randint(1, 5) for _ in tags]
    fills = rng.sample(PALETTE, 3)
    body = []
    for row, (gid, tag, n, f) in enumerate(zip(ids, tags, counts, fills)):
        cy = box[1] + box[3] * (row + 0.5) / 3
        body.append(f'<g id="{gid}">')
        for cx, w in _slots(box, n):
            s = min(w, box[3] / 3) * 0.3
            if tag == "circle":
                body.append(f'  <circle cx="{cx:g}" cy="{cy:g}" r="{s:g}" fill="{f}"/>')
            elif tag == "rect":
                body.append(f'  <rect x="{cx - s:g}" y="{cy - s:g}" width="{2 * s:g}" '
                            f'height="{2 * s:g}" fill="{f}"/>')
            else:
                body.append(f'  <ellipse cx="{cx:g}" cy="{cy:g}" rx="{s:g}" ry="{s / 2:g}" fill="{f}"/>')
        body.append("</g>")
    held = ", ".join(f'a <g id="{gid}"> holding exactly {n} <{tag}> filled {f}'
                     for gid, tag, n, f in zip(ids, tags, counts, fills))
    prompt = (f"Draw three groups: {held}. Each shape type goes only in its own group. "
              f"{FILLS} {NOTHING_ELSE}")
    spec = {"count": dict(zip(tags, counts)), "fill": dict(zip(tags, fills)),
            "groups": {gid: {t: (n if t == tag else 0) for t in tags}
                       for gid, tag, n in zip(ids, tags, counts)}}
    return "hard", prompt, spec, body, True


def _grid(rng, box):
    rows, cols = rng.randint(3, 6), rng.randint(3, 7)
    f1, f2 = rng.sample(PALETTE, 2)
    s = min(box[2] / cols, box[3] / rows)
    body, fills = [], []
    for r in range(rows):
        for c in range(cols):
            f = f1 if (r + c) % 2 == 0 else f2
            fills.append(f)
            body.append(f'<rect x="{box[0] + c * s:g}" y="{box[1] + r * s:g}" width="{s:g}" '
                        f'height="{s:g}" fill="{f}"/>')
    prompt = (f"On a viewBox of \"{_vb(box)}\", draw a checkerboard of {rows} rows by {cols} "
              f"columns of equal squares, one <rect> per square. The top-left square is {f1} and "
              f"squares alternate {f1} and {f2} along every row and column. {FILLS} "
              f"{NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"rect": rows * cols},
            "order": {"tag": "rect", "axis": "yx", "fills": fills}, "inside": True}
    return "hard", prompt, spec, body, True


def _legend(rng, box):
    n = rng.randint(3, 8)
    names = rng.sample(WORDS, n)
    fills = rng.sample(PALETTE, n)
    step = box[3] / n
    s = step * 0.6
    body = []
    for i, (name, f) in enumerate(zip(names, fills)):
        y = box[1] + i * step + (step - s) / 2
        body.append(f'<rect x="{box[0] + 4:g}" y="{y:g}" width="{s:g}" height="{s:g}" fill="{f}"/>')
        body.append(f'<text x="{box[0] + 8 + s:g}" y="{y + s * 0.8:g}" font-size="{s * 0.8:g}">'
                    f'{name}</text>')
    pairs = "; ".join(f"{f} labelled \"{name}\"" for name, f in zip(names, fills))
    prompt = (f"Draw a chart legend on a viewBox of \"{_vb(box)}\": {n} rows from top to bottom, "
              f"each one square <rect> swatch with its label in a <text> beside it: {pairs}. "
              f"Exactly {n} <rect> and {n} <text>. {FILLS} {NO_TRANSFORM} {NOTHING_ELSE}")
    spec = {"viewbox": list(box), "count": {"rect": n, "text": n},
            "order": {"tag": "rect", "axis": "yx", "fills": fills}, "labels": names, "inside": True}
    return "hard", prompt, spec, body, True


#: Kind -> scene drawer; each returns (stratum, prompt, structure, reference body, llm only).
KINDS = {"dots": _dots, "blobs": _blobs, "row": _row, "mix": _mix, "closed": _closed,
         "badge": _badge, "bars": _bars, "groups": _groups, "grid": _grid, "legend": _legend,
         "ring": _ring, "clock": _clock, "concentric": _concentric}


def scene(row: dict):
    """The drawn scene of one row: (stratum, prompt, structure, reference svg, llm only)."""
    rng = random.Random(f"{_KEY}:{VERSION}:{row['seed']}:{row['item']}:{row['attempt']}")
    box = VIEWBOXES[rng.randrange(len(VIEWBOXES))]
    stratum, prompt, spec, body, llm_only = KINDS[row["kind"]](rng, box)
    return stratum, prompt, spec, _svg(box, body), llm_only


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, kinds in equal turn; a prompt already drawn is drawn again."""
    out, seen, kinds = [], set(), sorted(KINDS)
    for i in range(count):
        row = {"item": i, "seed": seed, "kind": kinds[i % len(kinds)], "attempt": 0}
        while scene(row)[1] in seen:
            row["attempt"] += 1
            if row["attempt"] > ATTEMPTS:
                raise ValueError(f"{row['kind']} has too few distinct prompts for {count} cases")
        seen.add(scene(row)[1])
        out.append(row)
    return out


def case_of(row: dict) -> dict:
    stratum, prompt, spec, _, llm_only = scene(row)
    att = provenance(sys.modules[__name__], row["item"],
                     "a seeded scene described as a prompt, asserted on its structure")
    att.update(version=VERSION, seed=row["seed"], kind=row["kind"], stratum=stratum)
    case = {"id": f"svg-synth-{row['item']:04d}", "modality": LANE, "prompt": prompt}
    if llm_only:
        case["methods"] = ["llm"]
    case.update({"assert": {"structure": spec}, "attribution": att})
    return case


def convert(row: dict) -> Imported:
    case = case_of(row)
    return Imported(case, files=((f"reference/{case['id']}.svg", scene(row)[3].encode("utf-8")),))


def reference(case) -> str:
    """The generator's own drawing of a committed case, beside it under reference/."""
    return (case.source.parent / "reference" / f"{case.id}.svg").read_text(encoding="utf-8")


def _other(case) -> str:
    n = int(case.id.rsplit("-", 1)[1])
    path = case.source.parent / "reference" / f"svg-synth-{(n + 1) % COUNT:04d}.svg"
    return path.read_text(encoding="utf-8")


#: The negative control: the reference drawing passes; one blank square or another case's drawing does not.
RESPONDERS = {
    "reference": reference,
    "square": lambda case: _svg((0, 0, 100, 100), ['<rect x="10" y="10" width="80" height="80"/>']),
    "other-case": _other,
}


def passes(case, svg: str) -> bool:
    """What the svg checker decides on `svg`, structure and parse, without rasterizing."""
    from harness.checks import svg as svg_check
    return svg_check.check(svg).ok and not svg_check.structure(
        svg, case.assertions.get("structure") or {})
