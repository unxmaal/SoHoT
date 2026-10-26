"""A person's labels against the staging detector: the sheet, the agreement table, the night run (#1244)."""
from __future__ import annotations

import csv
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

from harness.checks import staging
from harness.intervals import wilson

COLUMNS = ("item", "image", "requirement", "type", "question", "label")
CANDIDATES = ("mflux:dev", "mflux:z-image-turbo", "mflux:flux2-klein-4b", "mflux:z-image")
SEEDS = 3
YES, NO, UNSURE = "y", "n", "?"


def _images(run: Path) -> list[dict]:
    """Every staging row of a run that left a sidecar: its image, candidate and verdicts."""
    payload = json.loads((run / "results.json").read_text(encoding="utf-8"))
    out = []
    for row in payload.get("rows") or ():
        path = row.get("artifact_path") or ""
        if not path:
            continue
        image = Path(path) if Path(path).is_absolute() else run / path
        side = staging.sidecar(image)
        if image.is_file() and side.is_file():
            out.append({"source": image, "candidate": row.get("candidate") or "", "case": row.get("case_id") or "",
                        "verdicts": json.loads(side.read_text(encoding="utf-8"))["verdicts"]})
    return sorted(out, key=lambda r: str(r["source"]))


def pick(images: list[dict], n: int, seed: int = 0) -> list[dict]:
    """n images, round robin over candidates, each turn taking the image whose types are least covered so far."""
    rng = random.Random(seed)
    pools: dict[str, list[dict]] = defaultdict(list)
    for im in images:
        pools[im["candidate"]].append(im)
    for pool in pools.values():
        rng.shuffle(pool)
    seen: dict[str, int] = defaultdict(int)
    chosen: list[dict] = []
    order = sorted(pools)
    while len(chosen) < n and any(pools.values()):
        for cand in order:
            pool = pools[cand]
            if not pool or len(chosen) >= n:
                continue
            best = max(pool, key=lambda im: sum(1 / (1 + seen[v["type"]]) for v in im["verdicts"]))
            pool.remove(best)
            chosen.append(best)
            for v in best["verdicts"]:
                seen[v["type"]] += 1
    return chosen


def sheet(run: str | Path, n: int = 30, out: str | Path = "staging-sheet.csv", seed: int = 0) -> list[dict]:
    """Copy n images under neutral names beside a CSV of yes/no questions; the key stays in a JSON file."""
    run, out = Path(run), Path(out)
    chosen = pick(_images(run), n, seed)
    folder = out.parent / f"{out.stem}-images"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, im in enumerate(chosen, 1):
        name = f"item-{i:02d}{im['source'].suffix}"
        shutil.copyfile(im["source"], folder / name)
        for v in im["verdicts"]:
            rows.append({"item": i, "image": f"{folder.name}/{name}", "requirement": v["index"], "type": v["type"],
                         "question": v["question"], "label": "", "source": str(im["source"]),
                         "candidate": im["candidate"], "case": im["case"]})
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    key = {str(r["item"]): {"source": r["source"], "candidate": r["candidate"], "case": r["case"]} for r in rows}
    _key(out).write_text(json.dumps(key, indent=1), encoding="utf-8")
    return rows


def _key(out: Path) -> Path:
    return out.with_suffix(".key.json")


def agreement(sheet_path: str | Path, run: str | Path | None = None) -> list[dict]:
    """Precision and recall of the detector's 'met' against the person's, per requirement type, with intervals."""
    sheet_path = Path(sheet_path)
    key = json.loads(_key(sheet_path).read_text(encoding="utf-8"))
    with sheet_path.open(newline="", encoding="utf-8") as f:
        labelled = [r for r in csv.DictReader(f) if r["label"].strip().lower() in (YES, NO)]
    if not labelled:
        raise ValueError(f"{sheet_path}: no labels yet; mark each row y, n or ?")
    verdicts: dict[str, list] = {}
    cells: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for r in labelled:
        source = key[r["item"]]["source"]
        if source not in verdicts:
            verdicts[source] = json.loads(staging.sidecar(Path(source)).read_text(encoding="utf-8"))["verdicts"]
        detector = bool(verdicts[source][int(r["requirement"])]["ok"])
        cells[r["type"]].append((detector, r["label"].strip().lower() == YES))
    table = []
    for kind in [t for t in staging.TYPES if t in cells]:
        pairs = cells[kind]
        tp = sum(d and p for d, p in pairs)
        said = sum(d for d, _ in pairs)
        real = sum(p for _, p in pairs)
        precision = round(tp / said, 4) if said else 0.0
        recall = round(tp / real, 4) if real else 0.0
        table.append({"type": kind, "n": len(pairs), "tp": tp, "detector_met": said, "person_met": real,
                      "precision": precision, "precision_interval": wilson(tp, said),
                      "recall": recall, "recall_interval": wilson(tp, real),
                      "counted": precision >= staging.MIN_AGREEMENT and recall >= staging.MIN_AGREEMENT})
    return table


def night() -> list[str]:
    """The paired night run: four candidates, three seeds, the whole image lane."""
    return ["uv", "run", "--group", "metrics", "python", "-m", "evals.run", "--modality", "image",
            "--candidates", ",".join(CANDIDATES), "--repeat", str(SEEDS)]
