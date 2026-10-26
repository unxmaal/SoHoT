"""Checker controls for the staging check: drawn scenes with known boxes, and one-requirement breaks (#1244)."""
from __future__ import annotations

from dataclasses import dataclass, replace

from harness.checks import staging

SIZE = 512
COLOURS = {"red": (200, 30, 30), "blue": (30, 60, 200), "green": (30, 160, 60), "yellow": (230, 190, 20)}
BACKGROUND = (235, 235, 230)


@dataclass(frozen=True)
class Shape:
    label: str
    kind: str
    colour: str
    box: tuple[int, int, int, int]

    @property
    def description(self) -> str:
        return f"a {self.colour} {self.kind}"


@dataclass(frozen=True)
class Scene:
    name: str
    spec: dict
    shapes: tuple[Shape, ...]
    #: Indices of the requirements this scene must fail; empty for a reference.
    fails: tuple[int, ...] = ()


def _s(label, kind, colour, box):
    return Shape(label, kind, colour, box)


LAYOUT = {
    "objects": {"circle": "a red circle", "square": "a blue square", "triangle": "a green triangle"},
    "require": [{"type": "count", "object": "circle", "n": 2},
                {"type": "count", "object": "square", "n": 1},
                {"type": "side", "object": "circle", "side": "left"},
                {"type": "side", "object": "square", "side": "right"},
                {"type": "above", "object": "triangle", "over": "square"}],
}
SIZES = {
    "objects": {"circle": "a red circle", "square": "a blue square", "triangle": "a green triangle"},
    "require": [{"type": "bigger", "object": "circle", "than": "square"},
                {"type": "frame", "object": "triangle", "max": 0.05},
                {"type": "frame", "object": "circle", "min": 0.15}],
}
ATTRIBUTES = {
    "objects": {"circle": "a circle", "square": "a blue square", "star": "a yellow star",
                "triangle": "a green triangle"},
    "require": [{"type": "attribute", "object": "circle", "is": "a red circle", "not": "a blue circle"},
                {"type": "held", "object": "star", "by": "square"},
                {"type": "count", "object": "triangle", "n": 0},
                {"type": "count", "object": "circle", "n": 1}],
}

_LAYOUT = (_s("circle", "circle", "red", (40, 330, 140, 430)), _s("circle", "circle", "red", (150, 340, 230, 420)),
           _s("square", "square", "blue", (330, 260, 450, 380)), _s("triangle", "triangle", "green", (340, 90, 440, 190)))
_SIZES = (_s("circle", "circle", "red", (20, 20, 250, 250)), _s("square", "square", "blue", (340, 360, 420, 440)),
          _s("triangle", "triangle", "green", (400, 40, 460, 100)))
_ATTRIBUTES = (_s("circle", "circle", "red", (60, 200, 180, 320)), _s("square", "square", "blue", (280, 180, 480, 380)),
               _s("star", "star", "yellow", (330, 230, 430, 330)))


def _swap(shapes, i, shape):
    return tuple(shape if j == i else s for j, s in enumerate(shapes))


def scenes() -> list[Scene]:
    """Three references, then one break per requirement of each, each failing exactly that requirement."""
    lay, siz, att = _LAYOUT, _SIZES, _ATTRIBUTES
    return [
        Scene("layout", LAYOUT, lay),
        Scene("layout-three-circles", LAYOUT, lay + (_s("circle", "circle", "red", (60, 180, 130, 250)),), (0,)),
        Scene("layout-two-squares", LAYOUT, lay + (_s("square", "square", "blue", (300, 420, 370, 490)),), (1,)),
        Scene("layout-circle-on-the-right", LAYOUT, _swap(lay, 1, replace(lay[1], box=(280, 400, 360, 480))), (2,)),
        Scene("layout-square-on-the-left", LAYOUT,
              _swap(_swap(lay, 2, replace(lay[2], box=(60, 140, 170, 250))), 3, replace(lay[3], box=(65, 20, 165, 110))),
              (3,)),
        Scene("layout-triangle-below", LAYOUT, _swap(lay, 3, replace(lay[3], box=(340, 400, 440, 500))), (4,)),
        Scene("sizes", SIZES, siz),
        Scene("sizes-square-as-big", SIZES, _swap(siz, 1, replace(siz[1], box=(260, 260, 500, 500))), (0,)),
        Scene("sizes-triangle-too-big", SIZES, _swap(siz, 2, replace(siz[2], box=(300, 20, 500, 220))), (1,)),
        Scene("sizes-circle-too-small", SIZES, _swap(siz, 0, replace(siz[0], box=(60, 60, 160, 160))), (2,)),
        Scene("attributes", ATTRIBUTES, att),
        Scene("attributes-blue-circle", ATTRIBUTES, _swap(att, 0, replace(att[0], colour="blue")), (0,)),
        Scene("attributes-star-outside", ATTRIBUTES, _swap(att, 2, replace(att[2], box=(60, 380, 160, 480))), (1,)),
        Scene("attributes-a-triangle", ATTRIBUTES, att + (_s("triangle", "triangle", "green", (60, 40, 160, 140)),),
              (2,)),
        Scene("attributes-two-circles", ATTRIBUTES, att + (_s("circle", "circle", "red", (200, 400, 280, 480)),), (3,)),
    ]


def render(scene: Scene):
    """The scene drawn flat on a plain background, at the lane's resolution."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (SIZE, SIZE), BACKGROUND)
    d = ImageDraw.Draw(im)
    for s in scene.shapes:
        x0, y0, x1, y1 = s.box
        fill = COLOURS[s.colour]
        if s.kind == "circle":
            d.ellipse(s.box, fill=fill)
        elif s.kind == "square":
            d.rectangle(s.box, fill=fill)
        elif s.kind == "triangle":
            d.polygon([((x0 + x1) / 2, y0), (x1, y1), (x0, y1)], fill=fill)
        else:
            d.polygon(_star(s.box), fill=fill)
    return im


def _star(box):
    import math
    x0, y0, x1, y1 = box
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def known_boxes(scene: Scene) -> list[staging.Box]:
    """The boxes a perfect detector would return, with a clear contrast on every probe."""
    probes = staging.probes(scene.spec)
    return [staging.Box(s.label, 0.9, s.box[0] / SIZE, s.box[1] / SIZE, s.box[2] / SIZE, s.box[3] / SIZE,
                        {q: 0.9 if q == s.description else 0.1 for q in probes}) for s in scene.shapes]


def failed(verdicts) -> tuple[int, ...]:
    return tuple(v.index for v in verdicts if not v.ok)


def run(dev: str | None = None, detector: bool = True) -> list[dict]:
    """Each scene's expected and observed failures, from the detector or from the known boxes."""
    rows = []
    for scene in scenes():
        if detector:
            boxes = staging.detect(render(scene), scene.spec["objects"], staging.probes(scene.spec), dev)
        else:
            boxes = known_boxes(scene)
        verdicts = staging.evaluate(scene.spec, boxes, uncounted=())
        rows.append({"scene": scene.name, "expected": list(scene.fails), "failed": list(failed(verdicts)),
                     "ok": failed(verdicts) == scene.fails, "boxes": boxes,
                     "details": [v.detail for v in verdicts]})
    return rows


def device_gap(cpu: list[dict], mps: list[dict]) -> float:
    """The largest box-coordinate difference between two devices' runs, inf when boxes differ in number or label."""
    worst = 0.0
    for a, b in zip(cpu, mps, strict=True):
        if [x.label for x in a["boxes"]] != [x.label for x in b["boxes"]]:
            return float("inf")
        for x, y in zip(a["boxes"], b["boxes"]):
            worst = max(worst, abs(x.x0 - y.x0), abs(x.y0 - y.y0), abs(x.x1 - y.x1), abs(x.y1 - y.y1))
    return worst
