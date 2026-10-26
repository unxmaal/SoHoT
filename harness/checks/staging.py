"""Does the picture stage what was asked: counts, sides, above, sizes, attributes, held objects (#1244).

An open-vocabulary detector (OWLv2, pinned) returns boxes and the requirements are judged from box
geometry, as GenEval and T2I-CompBench do with their closed-set detectors.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness import reasons
from harness.checks.base import CheckResult

DETECTOR_REPO = "google/owlv2-base-patch16-ensemble"
DETECTOR_REVISION = "cfd3195ba4ea9592eec887ded089f4c08eff231d"
WEIGHT_FILES = ["*.json", "*.txt", "model.safetensors"]
#: Bumped whenever a requirement's rule changes, so older verdicts are a different exam.
CHECKER_VERSION = 1
TYPES = ("count", "side", "above", "bigger", "frame", "attribute", "held")
#: Requirement types reported but left out of the pass: those whose detector agreement is under MIN_AGREEMENT.
UNCOUNTED: frozenset[str] = frozenset()
DEVICES = ("cpu", "mps")

DETECT_THRESHOLD = 0.3
NMS_IOU = 0.3
POSITION_MARGIN = 0.1
SIDE_MARGIN = 0.05
BIGGER_RATIO = 1.2
HELD_OVERLAP = 0.5
ATTRIBUTE_MARGIN = 0.0
MIN_AGREEMENT = 0.8
DEVICE_BOX_TOLERANCE = 0.01

_CACHE: dict[str, object] = {}


class DetectorUnavailable(RuntimeError):
    """torch, transformers or the pinned detector weights are not here."""


@dataclass(frozen=True)
class Box:
    label: str
    score: float
    x0: float
    y0: float
    x1: float
    y1: float
    #: Every probe query's score on this same box, for attribute requirements.
    probes: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def w(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def h(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class Verdict:
    index: int
    type: str
    question: str
    ok: bool
    detail: str = ""
    counted: bool = True


def validate(spec) -> None:
    """Refuse a staging assertion that names an unknown type, object or field."""
    if not isinstance(spec, dict) or not isinstance(spec.get("objects"), dict) or not spec["objects"]:
        raise ValueError("assert.staging needs objects: {name: detector query}")
    objects = spec["objects"]
    for name, query in objects.items():
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"staging object {name!r} needs a detector query")
    require = spec.get("require")
    if not isinstance(require, list) or not require:
        raise ValueError("assert.staging needs require: a list of requirements")
    allowed = {"count": {"n"}, "side": {"side"}, "above": {"over"}, "bigger": {"than"},
               "frame": {"min", "max"}, "attribute": {"is", "not"}, "held": {"by"}}
    for i, r in enumerate(require):
        kind = r.get("type") if isinstance(r, dict) else None
        if kind not in TYPES:
            raise ValueError(f"staging requirement {i}: type {kind!r} is not one of {', '.join(TYPES)}")
        extra = set(r) - {"type", "object"} - allowed[kind]
        if extra:
            raise ValueError(f"staging requirement {i} ({kind}): unknown field(s) {', '.join(sorted(extra))}")
        if r.get("object") not in objects:
            raise ValueError(f"staging requirement {i} ({kind}): object {r.get('object')!r} is not in objects")
        for ref in ("over", "than", "by"):
            if ref in allowed[kind] and r.get(ref) not in objects:
                raise ValueError(f"staging requirement {i} ({kind}): {ref} {r.get(ref)!r} is not in objects")
        if kind == "count" and (not isinstance(r.get("n"), int) or r["n"] < 0):
            raise ValueError(f"staging requirement {i} (count): n must be a whole number")
        if kind == "side" and r.get("side") not in ("left", "right"):
            raise ValueError(f"staging requirement {i} (side): side must be left or right")
        if kind == "frame" and not ({"min", "max"} & set(r)):
            raise ValueError(f"staging requirement {i} (frame): needs min or max, a share of the frame")
        if kind == "attribute" and not (str(r.get("is") or "").strip() and str(r.get("not") or "").strip()):
            raise ValueError(f"staging requirement {i} (attribute): needs is and not, two contrasting queries")


def probes(spec) -> list[str]:
    """The attribute queries scored on each kept box, besides the object queries."""
    out: list[str] = []
    for r in spec["require"]:
        if r["type"] == "attribute":
            out += [q for q in (r["is"], r["not"]) if q not in out]
    return out


def question(r: dict, objects: dict) -> str:
    """The requirement as a yes-or-no question a person can answer from the picture."""
    o = r["object"]
    kind = r["type"]
    if kind == "count":
        return f"Are there exactly {r['n']} of: {objects[o]}?"
    if kind == "side":
        return f"Is every {objects[o]} in the {r['side']} half of the frame?"
    if kind == "above":
        return f"Is the {objects[o]} above the {objects[r['over']]}?"
    if kind == "bigger":
        return f"Is the {objects[o]} clearly bigger in the frame than the {objects[r['than']]}?"
    if kind == "frame":
        bounds = " and ".join(f"{k} {int(r[k] * 100)}%" for k in ("min", "max") if k in r)
        return f"Does the {objects[o]} take up {bounds} of the frame?"
    if kind == "attribute":
        return f"Is it {r['is']} rather than {r['not']}?"
    return f"Is the {objects[o]} held by the {objects[r['by']]}?"


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union > 0 else 0.0


def inside(a: Box, b: Box) -> float:
    """Share of box a's area that lies within box b."""
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return ix * iy / a.area if a.area > 0 else 0.0


def above(a: Box, b: Box, margin: float | None = None) -> bool:
    """GenEval's relative_position: the centre offset less a margin of both sizes, read as a direction."""
    m = POSITION_MARGIN if margin is None else margin
    dx, dy = a.cx - b.cx, a.cy - b.cy
    rx = max(abs(dx) - m * (a.w + b.w), 0.0) * (1 if dx >= 0 else -1)
    ry = max(abs(dy) - m * (a.h + b.h), 0.0) * (1 if dy >= 0 else -1)
    if abs(rx) < 1e-3 and abs(ry) < 1e-3:
        return False
    norm = (dx * dx + dy * dy) ** 0.5
    return ry / norm < -0.5


def suppress(boxes: list[Box], limit: float | None = None) -> list[Box]:
    """Greedy non-maximum suppression within each label, highest score first."""
    limit = NMS_IOU if limit is None else limit
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.score):
        if all(k.label != b.label or iou(k, b) <= limit for k in kept):
            kept.append(b)
    return kept


def evaluate(spec: dict, boxes: list[Box], uncounted=None) -> list[Verdict]:
    """One verdict per requirement, from boxes in frame-normalised coordinates."""
    uncounted = UNCOUNTED if uncounted is None else frozenset(uncounted)
    objects = spec["objects"]
    found: dict[str, list[Box]] = {name: [] for name in objects}
    for b in sorted(boxes, key=lambda b: -b.score):
        if b.label in found:
            found[b.label].append(b)
    out = []
    for i, r in enumerate(spec["require"]):
        ok, detail = _one(r, found, objects)
        out.append(Verdict(i, r["type"], question(r, objects), ok, detail, r["type"] not in uncounted))
    return out


def _one(r: dict, found: dict, objects: dict) -> tuple[bool, str]:
    kind, name = r["type"], r["object"]
    mine = found[name]
    if kind == "count":
        return len(mine) == r["n"], f"found {len(mine)} {name}, asked {r['n']}"
    if not mine:
        return False, f"no {name} found"
    best = mine[0]
    if kind == "side":
        off = [b for b in mine if not (b.cx < 0.5 - SIDE_MARGIN if r["side"] == "left" else b.cx > 0.5 + SIDE_MARGIN)]
        return not off, f"{name} centre x {', '.join(f'{b.cx:.2f}' for b in mine)}, asked {r['side']}"
    other_name = r.get("over") or r.get("than") or r.get("by")
    others = found.get(other_name, []) if other_name else []
    if kind in ("above", "bigger", "held") and not others:
        return False, f"no {other_name} found"
    if kind == "above":
        bad = [(a, b) for a in mine for b in others if not above(a, b)]
        return not bad, f"{name} centre y {best.cy:.2f}, {other_name} centre y {others[0].cy:.2f}"
    if kind == "bigger":
        ratio = best.area / others[0].area if others[0].area else float("inf")
        return ratio > BIGGER_RATIO, f"{name} area {best.area:.3f} is {ratio:.2f}x {other_name}, asked over {BIGGER_RATIO}x"
    if kind == "frame":
        share = best.area
        ok = share >= r.get("min", 0.0) and share <= r.get("max", 1.0)
        return ok, f"{name} covers {share:.2f} of the frame"
    if kind == "attribute":
        yes, no = best.probes.get(r["is"], 0.0), best.probes.get(r["not"], 0.0)
        return yes > no + ATTRIBUTE_MARGIN, f"{r['is']!r} {yes:.3f} vs {r['not']!r} {no:.3f} on the {name} box"
    share = max(inside(best, b) for b in others)
    return share >= HELD_OVERLAP, f"{share:.2f} of the {name} box lies in a {other_name} box, asked {HELD_OVERLAP}"


def device() -> str:
    """The torch device: SOH_STAGING_DEVICE if set, else MPS where torch has it, else CPU."""
    chosen = os.environ.get("SOH_STAGING_DEVICE", "").strip()
    if chosen:
        if chosen not in DEVICES:
            raise ValueError(f"SOH_STAGING_DEVICE={chosen!r} is not one of {', '.join(DEVICES)}")
        return chosen
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def weights() -> str:
    """The pinned snapshot's directory: the cached copy if whole, else downloaded once."""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        return snapshot_download(DETECTOR_REPO, revision=DETECTOR_REVISION, allow_patterns=WEIGHT_FILES,
                                 local_files_only=True)
    except LocalEntryNotFoundError:
        return snapshot_download(DETECTOR_REPO, revision=DETECTOR_REVISION, allow_patterns=WEIGHT_FILES)


def _detector(dev: str):
    if dev not in _CACHE:
        try:
            import torch
            from transformers import Owlv2ForObjectDetection, Owlv2Processor
        except ImportError as exc:
            raise DetectorUnavailable(f"{exc}; install with: uv sync --group metrics") from exc
        try:
            local = weights()
            processor = Owlv2Processor.from_pretrained(local)
            model = Owlv2ForObjectDetection.from_pretrained(local)
        except OSError as exc:
            raise DetectorUnavailable(f"{DETECTOR_REPO}@{DETECTOR_REVISION[:8]}: {exc}") from exc
        _CACHE[dev] = (processor, model.eval().to(dev), torch)
    return _CACHE[dev]


def detect(image, objects: dict, extra: list[str] = (), dev: str | None = None) -> list[Box]:
    """Boxes labelled with the object query that scores highest on them, over the threshold, suppressed."""
    from PIL import Image
    dev = dev or device()
    processor, model, torch = _detector(dev)
    if not isinstance(image, Image.Image):
        with Image.open(image) as im:
            image = im.convert("RGB")
    else:
        image = image.convert("RGB")
    names = list(objects)
    queries = [objects[n] for n in names]
    probe_queries = [q for q in extra if q not in queries]
    every = queries + probe_queries
    inputs = processor(text=[every], images=image, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inputs)
    scores = torch.sigmoid(out.logits[0].float()).cpu()
    pred = out.pred_boxes[0].float().cpu()
    width, height = image.size
    side = max(width, height)
    best, label = scores[:, :len(queries)].max(-1)
    candidates = []
    for i in torch.nonzero(best >= DETECT_THRESHOLD).flatten().tolist():
        cx, cy, w, h = (v * side for v in pred[i].tolist())
        candidates.append(Box(
            names[label[i]], round(float(best[i]), 4),
            round(max(0.0, (cx - w / 2) / width), 4), round(max(0.0, (cy - h / 2) / height), 4),
            round(min(1.0, (cx + w / 2) / width), 4), round(min(1.0, (cy + h / 2) / height), 4),
            {q: round(float(scores[i, every.index(q)]), 4) for q in extra}))
    return suppress(candidates)


def check(path: str | Path, spec: dict, dev: str | None = None) -> CheckResult:
    """Detect, judge every requirement, write the boxes and verdicts beside the image."""
    path = Path(path)
    try:
        dev = dev or device()
        boxes = detect(path, spec["objects"], probes(spec), dev)
    except DetectorUnavailable as exc:
        return CheckResult(False, f"staging not judged: {exc}", failure_class=reasons.MISSING_PACKAGE)
    verdicts = evaluate(spec, boxes)
    counted = [v for v in verdicts if v.counted]
    met = sum(v.ok for v in counted)
    sidecar(path).write_text(json.dumps({
        "detector": f"{DETECTOR_REPO}@{DETECTOR_REVISION}", "checker": CHECKER_VERSION, "device": dev,
        "boxes": [asdict(b) for b in boxes], "verdicts": [asdict(v) for v in verdicts]}, indent=1), encoding="utf-8")
    result = CheckResult(met == len(counted), "")
    result.metrics = {"staging": round(met / len(counted), 4) if counted else 0.0}
    if not result.ok:
        result.reason = "staging: " + "; ".join(f"{v.type}: {v.detail}" for v in counted if not v.ok)
    return result


def sidecar(path: Path) -> Path:
    return Path(path).with_suffix(".staging.json")
