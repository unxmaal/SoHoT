"""Is this actually a usable SVG?

Ordered by how badly each failure wastes the reader's time: unparseable is
worthless, an empty canvas is worthless, and a raster in a data: URI is a
bitmap wearing a vector's clothes.
"""
from __future__ import annotations

import math
import re
from xml.etree import ElementTree

from .base import CheckResult, extract

SVG_NS = "{http://www.w3.org/2000/svg}"
# Elements that put marks on the canvas. `defs`, `title`, `metadata` do not.
DRAWING = {"path", "circle", "rect", "ellipse", "line", "polyline", "polygon",
           "text", "use", "image", "g"}


#: Attributes that, at zero, make a shape invisible whatever else it has.
_EXTENT_ATTRS = {"rect": ("width", "height"), "circle": ("r",),
                 "ellipse": ("rx", "ry"), "line": (), "path": (),
                 "polyline": (), "polygon": (), "text": ()}


def _has_extent(el) -> bool:
    """False for a shape that cannot mark the canvas at any zoom."""
    name = el.tag.replace(SVG_NS, "")
    attrs = _EXTENT_ATTRS.get(name)
    if not attrs:
        # path/line/polygon have no size attribute; an empty `d` is the
        # equivalent and the only one worth catching cheaply.
        if name in ("path",) and not (el.get("d") or "").strip():
            return False
        return True
    for a in attrs:
        raw = (el.get(a) or "").strip()
        if not raw:
            continue
        try:
            if float(raw.rstrip("px%")) == 0:
                return False
        except ValueError:
            continue
    return True


def check(text: str) -> CheckResult:
    src = extract(text, ("svg",))
    if not src.strip():
        return CheckResult(False, "no SVG found in output")

    try:
        root = ElementTree.fromstring(src)
    except ElementTree.ParseError as exc:
        return CheckResult(False, f"XML parse error: {exc}")

    tag = root.tag.replace(SVG_NS, "")
    if tag != "svg":
        return CheckResult(False, f"root element is <{tag}>, not <svg>")

    shapes = [e for e in root.iter()
              if e.tag.replace(SVG_NS, "") in DRAWING and e is not root]
    # A <g> alone draws nothing; require at least one real mark.
    marks = [e for e in shapes if e.tag.replace(SVG_NS, "") != "g"]
    # NOR DOES A SHAPE WITH NO EXTENT. Eight `<rect width="0" height="0"/>`
    # satisfied `min_shapes: 6` and passed the case. The rasterizer catches a
    # wholly blank document, but not six real marks padded out with eight
    # invisible ones, and the count is what the assertion reads.
    marks = [e for e in marks if _has_extent(e)]

    warnings: list[str] = []
    if not root.get("viewBox"):
        warnings.append("no viewBox: will not scale cleanly")
    if not root.get("xmlns") and SVG_NS not in root.tag:
        warnings.append("no xmlns: may not render standalone")
    if re.search(r'data:image/(png|jpe?g|gif|webp)', src, re.I):
        warnings.append("embedded raster image: not really a vector")

    if not marks:
        return CheckResult(False, "SVG draws nothing", warnings, shape_count=0)

    return CheckResult(True, "", warnings, shape_count=len(marks))


#: Containers whose children are definitions, not marks on the canvas.
_HIDDEN = {"defs", "clipPath", "mask", "symbol", "marker", "pattern", "linearGradient",
           "radialGradient", "filter"}
#: The keys a case's `structure` assertion may carry. #1050.
STRUCTURE_KEYS = {"viewbox", "count", "marks", "tally", "fill", "order", "labels", "closed", "groups",
                  "heights", "inside", "ring", "hands", "stack"}
#: How far a coordinate may sit from where the case puts it, in user units.
COORD_TOLERANCE = 1.0
#: How far a clock hand may point from its true angle, in degrees.
ANGLE_TOLERANCE = 4.0
_RGB = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def validate_structure(spec) -> None:
    """Refuse a structure assertion with a key the checker cannot read."""
    if not isinstance(spec, dict):
        raise ValueError("structure must be a mapping")
    unknown = set(spec) - STRUCTURE_KEYS
    if unknown:
        raise ValueError(f"unknown structure key(s): {', '.join(sorted(unknown))}")
    if "order" in spec and spec["order"].get("axis") not in ("x", "yx"):
        raise ValueError(f"structure.order.axis must be x or yx, not {spec['order'].get('axis')!r}")


def _name(el) -> str:
    return el.tag.replace(SVG_NS, "") if isinstance(el.tag, str) else ""


def colour(raw: str | None) -> str:
    """A fill value in one spelling: lowercase #rrggbb where it is a colour."""
    v = (raw or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return "#" + "".join(ch * 2 for ch in v[1:])
    m = _RGB.fullmatch(v)
    if m:
        return "#" + "".join(f"{min(int(g), 255):02x}" for g in m.groups())
    return v


def _own_fill(el) -> str | None:
    for part in (el.get("style") or "").split(";"):
        key, _, val = part.partition(":")
        if key.strip() == "fill" and val.strip():
            return val.strip()
    return el.get("fill")


def _marks(root):
    """(element, effective fill, ancestors) for each visible shape outside definitions."""
    out = []

    def walk(el, fill, chain):
        name = _name(el)
        if name in _HIDDEN:
            return
        own = _own_fill(el)
        here = own if own and own != "inherit" else fill
        if el is not root and name in DRAWING and name != "g" and _has_extent(el):
            out.append((el, colour(here), chain))
        for child in el:
            walk(child, here, chain + (el,))

    walk(root, "#000000", ())
    return out


def _num(el, attr: str) -> float:
    found = _NUM.findall(el.get(attr) or "")
    return float(found[0]) if found else 0.0


def _position(el) -> tuple[float, float]:
    name = _name(el)
    if name in ("circle", "ellipse"):
        return _num(el, "cx"), _num(el, "cy")
    return _num(el, "x"), _num(el, "y")


def _closed(d: str) -> bool:
    subpaths = [s.strip() for s in re.split(r"(?=[Mm])", d or "") if s.strip()]
    return bool(subpaths) and all(s[-1] in "Zz" for s in subpaths)


def _label(el) -> str:
    return " ".join("".join(el.itertext()).split())


def structure(text: str, spec: dict) -> str:
    """Why this SVG misses its case's structure assertion, or "" when it meets all of it."""
    if not spec:
        return ""
    validate_structure(spec)
    try:
        root = ElementTree.fromstring(extract(text, ("svg",)))
    except ElementTree.ParseError as exc:
        return f"XML parse error: {exc}"
    marks = _marks(root)
    by_tag: dict[str, list] = {}
    for m in marks:
        by_tag.setdefault(_name(m[0]), []).append(m)
    if "viewbox" in spec:
        got = [float(n) for n in _NUM.findall(root.get("viewBox") or "")]
        if got != [float(n) for n in spec["viewbox"]]:
            return f"viewBox is {root.get('viewBox')!r}, expected {' '.join(map(str, spec['viewbox']))!r}"
    if "marks" in spec and len(marks) != spec["marks"]:
        return f"expected exactly {spec['marks']} visible shapes, drew {len(marks)}"
    for tag, n in (spec.get("count") or {}).items():
        if len(by_tag.get(tag, [])) != n:
            return f"expected exactly {n} <{tag}>, drew {len(by_tag.get(tag, []))}"
    for want, n in (spec.get("tally") or {}).items():
        got = sum(1 for _, f, _ in marks if f == colour(want))
        if got != n:
            return f"expected exactly {n} shapes filled {colour(want)}, drew {got}"
    for tag, want in (spec.get("fill") or {}).items():
        pool = marks if tag == "*" else by_tag.get(tag, [])
        wrong = sorted({f for _, f, _ in pool if f != colour(want)})
        if wrong:
            return f"<{tag}> filled {', '.join(wrong)}, expected {colour(want)}"
    if set(spec) & {"order", "heights", "inside", "ring", "hands", "stack"} and any(e.get("transform") for e in root.iter()):
        return "uses a transform; positions are read from attributes and the case forbids one"
    order = spec.get("order")
    if order:
        key = (lambda m: _position(m[0])[0]) if order["axis"] == "x" else (
            lambda m: (round(_position(m[0])[1], 3), _position(m[0])[0]))
        got = [f for _, f, _ in sorted(by_tag.get(order["tag"], []), key=key)]
        if got != [colour(c) for c in order["fills"]]:
            return f"<{order['tag']}> fills in order {got}, expected {order['fills']}"
    if "heights" in spec:
        why = _heights(by_tag.get("rect", []), spec["heights"])
        if why:
            return why
    if spec.get("inside"):
        why = _inside(root, marks)
        if why:
            return why
    if "ring" in spec:
        why = _ring(by_tag.get("circle", []), spec["ring"])
        if why:
            return why
    if "hands" in spec:
        why = _hands(by_tag.get("line", []), spec["hands"])
        if why:
            return why
    if "stack" in spec:
        why = _stack(by_tag.get("circle", []), spec["stack"])
        if why:
            return why
    if "labels" in spec:
        got = sorted(_label(m[0]) for m in by_tag.get("text", []))
        if got != sorted(str(s) for s in spec["labels"]):
            return f"text reads {got}, expected {sorted(str(s) for s in spec['labels'])}"
    if "closed" in spec:
        paths = by_tag.get("path", [])
        shut = [m for m in paths if _closed(m[0].get("d"))]
        if len(paths) != spec["closed"] or len(shut) != len(paths):
            return (f"expected exactly {spec['closed']} closed <path>, drew {len(paths)} "
                    f"of which {len(shut)} closed")
    for gid, want in (spec.get("groups") or {}).items():
        group = next((g for g in root.iter() if _name(g) == "g" and g.get("id") == gid), None)
        if group is None:
            return f"no <g id={gid!r}>"
        for tag, n in want.items():
            inside = [m for m in by_tag.get(tag, []) if group in m[2]]
            if len(inside) != n:
                return f"<g id={gid!r}> holds {len(inside)} <{tag}>, expected {n}"
    return ""


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= COORD_TOLERANCE


def _heights(rects, want: dict) -> str:
    """Bars left to right stand on `base` with height value * `unit`."""
    bars = sorted(rects, key=lambda m: _position(m[0])[0])
    values = want["values"]
    if len(bars) != len(values):
        return f"expected {len(values)} bars, drew {len(bars)}"
    for (el, _, _), v in zip(bars, values):
        h, y = _num(el, "height"), _num(el, "y")
        if not _near(h, v * want["unit"]) or not _near(y + h, want["base"]):
            return (f"the bar for {v} spans y={y:g} to y={y + h:g}; expected "
                    f"{v * want['unit']:g} high standing on y={want['base']:g}")
    return ""


def _box(el):
    name = _name(el)
    if name == "rect":
        x, y = _position(el)
        return x, y, x + _num(el, "width"), y + _num(el, "height")
    if name in ("circle", "ellipse"):
        x, y = _position(el)
        rx = _num(el, "r") if name == "circle" else _num(el, "rx")
        ry = _num(el, "r") if name == "circle" else _num(el, "ry")
        return x - rx, y - ry, x + rx, y + ry
    if name == "line":
        xs, ys = (_num(el, "x1"), _num(el, "x2")), (_num(el, "y1"), _num(el, "y2"))
        return min(xs), min(ys), max(xs), max(ys)
    return None


def _inside(root, marks) -> str:
    vb = [float(n) for n in _NUM.findall(root.get("viewBox") or "")]
    if len(vb) != 4:
        return "no viewBox to stay inside"
    for el, _, _ in marks:
        box = _box(el)
        if box and (box[0] < vb[0] - COORD_TOLERANCE or box[1] < vb[1] - COORD_TOLERANCE
                    or box[2] > vb[0] + vb[2] + COORD_TOLERANCE
                    or box[3] > vb[1] + vb[3] + COORD_TOLERANCE):
            return f"<{_name(el)}> spills outside the viewBox"
    return ""


def _ring(circles, want: dict) -> str:
    """n circles centred evenly on a ring, the first straight above its centre, clockwise."""
    n, r = want["n"], want["r"]
    if len(circles) != n:
        return f"expected {n} circles on the ring, drew {len(circles)}"
    left = [_position(el) for el, _, _ in circles]
    for k in range(n):
        t = 2 * math.pi * k / n
        x, y = want["cx"] + r * math.sin(t), want["cy"] - r * math.cos(t)
        hit = next((p for p in left if _near(p[0], x) and _near(p[1], y)), None)
        if hit is None:
            return f"no circle at ({x:.1f}, {y:.1f}), position {k + 1} on the ring"
        left.remove(hit)
    return ""


def _angle(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dx, -dy)) % 360


def _hands(lines, want: dict) -> str:
    """Two lines from the centre: the shorter points at `hour`, the longer at `minute` degrees."""
    if len(lines) != 2:
        return f"expected 2 hands, drew {len(lines)} <line>"
    hands = []
    for el, _, _ in lines:
        ends = [(_num(el, "x1"), _num(el, "y1")), (_num(el, "x2"), _num(el, "y2"))]
        ends.sort(key=lambda p: math.dist(p, (want["cx"], want["cy"])))
        if not (_near(ends[0][0], want["cx"]) and _near(ends[0][1], want["cy"])):
            return "a hand does not start at the centre"
        dx, dy = ends[1][0] - want["cx"], ends[1][1] - want["cy"]
        hands.append((math.hypot(dx, dy), _angle(dx, dy)))
    (_, hour), (_, minute) = sorted(hands)
    for name, got, exp in (("hour", hour, want["hour"]), ("minute", minute, want["minute"])):
        off = abs((got - exp + 180) % 360 - 180)
        if off > ANGLE_TOLERANCE:
            return f"the {name} hand points at {got:.0f} degrees, expected {exp:g}"
    return ""


def _stack(circles, want: dict) -> str:
    """Concentric circles in paint order: radii and fills as listed, back to front."""
    got = [(_num(el, "r"), f) for el, f, _ in circles]
    if len(got) != len(want["radii"]):
        return f"expected {len(want['radii'])} circles, drew {len(got)}"
    for (el, _, _) in circles:
        if not (_near(_num(el, "cx"), want["cx"]) and _near(_num(el, "cy"), want["cy"])):
            return "the circles are not all centred on the given point"
    for (r, f), wr, wf in zip(got, want["radii"], want["fills"]):
        if not _near(r, wr) or f != colour(wf):
            return (f"circles in drawing order are {[(round(r, 1), f) for r, f in got]}, "
                    f"expected {list(zip(want['radii'], want['fills']))}")
    return ""
