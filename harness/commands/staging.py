"""`soh staging controls|sheet|agreement|night`: the staging detector's controls and its agreement with a person (#1244)."""
from __future__ import annotations

import shlex
from pathlib import Path

from harness import staging_controls, staging_labels
from harness.checks import staging
from harness.commands.common import emit, err, note


def _controls(a) -> int:
    devices = ["cpu", "mps"] if a.device == "both" else [a.device]
    runs = {}
    for dev in devices:
        rows = staging_controls.run(dev)
        runs[dev] = rows
        for r in rows:
            mark = "ok  " if r["ok"] else "FAIL"
            note(f"{mark} {dev} {r['scene']}: expected {r['expected'] or 'none'} failed, got {r['failed'] or 'none'}")
    good = all(r["ok"] for rows in runs.values() for r in rows)
    gap = None
    if len(runs) == 2:
        gap = staging_controls.device_gap(runs["cpu"], runs["mps"])
        same = [r["failed"] for r in runs["cpu"]] == [r["failed"] for r in runs["mps"]]
        good = good and same and gap <= staging.DEVICE_BOX_TOLERANCE
        note(f"mps vs cpu: verdicts {'identical' if same else 'DIFFER'}, largest box difference {gap:.4f} "
             f"(knob staging_device_tolerance {staging.DEVICE_BOX_TOLERANCE})")
    note(f"detector {staging.DETECTOR_REPO}@{staging.DETECTOR_REVISION[:8]}, checker {staging.CHECKER_VERSION}")
    emit(good, controls={d: [{k: r[k] for k in ("scene", "expected", "failed", "ok")} for r in rows]
                         for d, rows in runs.items()}, device_gap=gap)
    return 0 if good else 1


def _sheet(a) -> int:
    if not a.path:
        return err("staging sheet: name the night run's directory")
    rows = staging_labels.sheet(Path(a.path), n=a.n, out=Path(a.out), seed=a.seed)
    images = len({r["item"] for r in rows})
    note(f"{images} images, {len(rows)} questions in {a.out}; mark each label y, n or ? and run "
         f"`soh staging agreement {a.out}`")
    emit(True, images=images, questions=len(rows), sheet=a.out)
    return 0


def _agreement(a) -> int:
    table = staging_labels.agreement(Path(a.path or a.out))
    for t in table:
        p, r = t["precision_interval"], t["recall_interval"]
        note(f"{'counts ' if t['counted'] else 'REPORTS'} {t['type']:9s} n {t['n']:3d}  precision {t['precision']:.2f} "
             f"({p[0]:.2f}-{p[1]:.2f})  recall {t['recall']:.2f} ({r[0]:.2f}-{r[1]:.2f})")
    low = sorted(t["type"] for t in table if not t["counted"])
    if low:
        note(f"under staging_min_agreement {staging.MIN_AGREEMENT}: set staging.UNCOUNTED = {set(low)} in a PR")
    emit(True, agreement=table, uncounted=low)
    return 0


def _night(a) -> int:
    argv = staging_labels.night()
    note(f"from the deploy checkout: soh jobs --title 'staging #1244' add --night -- {shlex.join(argv)}")
    emit(True, night=argv)
    return 0


def cmd_staging(a) -> int:
    try:
        return {"controls": _controls, "sheet": _sheet, "agreement": _agreement, "night": _night}[a.action](a)
    except staging.DetectorUnavailable as exc:
        return err(f"staging: {exc}")
    except (OSError, ValueError, KeyError) as exc:
        return err(f"staging {a.action}: {exc}")
