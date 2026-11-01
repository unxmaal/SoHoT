"""GenEval's 553 object-composition prompts as image staging cases, judged by the pinned detector. #603.

Each row's include/exclude spec becomes staging requirements with GenEval's own meaning: an include
count is "at least", a counting row's include plus exclude is "exactly", a position names the other
object's relative place, and a colour must beat GenEval's nine other colours on the object's box.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from evals.importers import Imported, provenance

LANE = "image"
SOURCE = "github:djghosh13/geneval/prompts/evaluation_metadata.jsonl"
DATASET = "GenEval prompts (Ghosh, Hajishirzi, Schmidt 2023)"
LICENSE = "MIT"
REVISION = "af4902f24d3ca90ebbb446dd9891a59e0f82725f"
URL = f"https://github.com/djghosh13/geneval/blob/{REVISION}/prompts/evaluation_metadata.jsonl"
RAW = f"https://raw.githubusercontent.com/djghosh13/geneval/{REVISION}/prompts/evaluation_metadata.jsonl"
#: The file is unchanged since the commit that added it (d927da8e, 2023-08-22): every item's date.
ITEM_DATE = "2023-08-22"
RECORDED = Path(__file__).with_name("geneval.jsonl")
SHA256 = "5c48e0813e812e3c373fa5c8ed07a8f0a483be30272b4427b0559c8048e67c13"
COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white")
PARAMS = {"width": 512, "height": 512, "seed": 42}


def download(out: Path = RECORDED) -> Path:
    """Refresh the recorded copy from upstream at REVISION; refuses bytes with another digest."""
    with urllib.request.urlopen(RAW, timeout=60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError(f"{RAW} does not match the pinned sha256 {SHA256}")
    out.write_bytes(data)
    return out


def fetch() -> list[dict]:
    """The recorded rows at REVISION, numbered by line."""
    data = RECORDED.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError(f"{RECORDED.name} is not the pinned GenEval metadata; run download()")
    return [{**json.loads(line), "item": i} for i, line in enumerate(data.decode("utf-8").splitlines()) if line]


def _name(cls: str) -> str:
    return cls.replace(" ", "_")


def _require(row: dict) -> list[dict]:
    inc = row["include"]
    exact = {e["class"]: e["count"] - 1 for e in row.get("exclude", [])}
    out = []
    for e in inc:
        n = e["count"]
        if exact.get(e["class"]) == n:
            out.append({"type": "count", "object": _name(e["class"]), "n": n})
        else:
            out.append({"type": "count", "object": _name(e["class"]), "min": n})
    for e in inc:
        if "color" in e:
            noun = e["class"]
            out.append({"type": "attribute", "object": _name(noun), "is": f"a {e['color']} {noun}",
                        "not": [f"a {c} {noun}" for c in COLORS if c != e["color"]]})
    for e in inc:
        if "position" not in e:
            continue
        rel, idx = e["position"]
        me, other = _name(e["class"]), _name(inc[idx]["class"])
        out.append({"above": {"type": "above", "object": me, "over": other},
                    "below": {"type": "above", "object": other, "over": me},
                    "left of": {"type": "left_of", "object": me, "of": other},
                    "right of": {"type": "left_of", "object": other, "of": me}}[rel])
    return out


def convert(row: dict) -> Imported:
    objects = {_name(e["class"]): f"a {e['class']}" for e in row["include"]}
    att = provenance(sys.modules[__name__], row["item"],
                     "GenEval include/exclude spec as staging requirements: include count at least, include plus "
                     "exclude exactly, position relative to the named object, colour against the nine others",
                     date=ITEM_DATE)
    att["tag"] = row["tag"]
    case = {"id": f"geneval-{row['item']:03d}-{row['tag'].replace('_', '-')}", "modality": LANE,
            "prompt": row["prompt"], "params": dict(PARAMS),
            "assert": {"staging": {"objects": objects, "require": _require(row)}}, "attribution": att}
    return Imported(case)


def reference_boxes(spec: dict) -> list:
    """Boxes a perfect detector would return for a picture meeting `spec`, frame-normalised."""
    from harness.checks import staging
    names = list(spec["objects"])
    req = spec["require"]
    need = {r["object"]: r.get("n", r.get("min", 1)) for r in req if r["type"] == "count"}
    rel = next((r for r in req if r["type"] in ("above", "left_of")), None)
    cols = {n: i for i, n in enumerate(names)}
    if rel:
        a, b = rel["object"], rel.get("over") or rel.get("of")
        cols = {a: 0, b: 1}
    is_of = {r["object"]: r["is"] for r in req if r["type"] == "attribute"}
    probes = staging.probes(spec)
    boxes = []
    for name in names:
        c, k = cols[name], max(1, need.get(name, 1))
        for j in range(k):
            if rel and rel["type"] == "above":
                x0, y0 = 0.1 + 0.18 * j, 0.05 + 0.5 * c
            else:
                x0, y0 = 0.05 + 0.5 * c, 0.05 + 0.2 * j
            scores = {q: (0.9 if q == is_of.get(name) else 0.1) for q in probes}
            boxes.append(staging.Box(name, 0.9, x0, y0, x0 + 0.12, y0 + 0.12, scores))
    return boxes


def _reference(case):
    return reference_boxes(case.assertions["staging"])


def _other(case):
    rows = fetch()
    nxt = rows[(int(case.id.split("-")[1]) + 1) % len(rows)]
    return reference_boxes(convert(nxt).case["assert"]["staging"])


#: The negative control: boxes meeting the spec pass; no boxes, or the next case's boxes, do not.
RESPONDERS = {"reference": _reference, "empty": lambda case: [], "other-case": _other}


def passes(case, boxes) -> bool:
    """What the staging checker decides on these boxes, without the detector."""
    from harness.checks import staging
    return all(v.ok for v in staging.evaluate(case.assertions["staging"], boxes, uncounted=()))
