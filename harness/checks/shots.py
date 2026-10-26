"""Scoring detected shot boundaries against a clip's exact transitions, each type apart (#1208).

A detection matches at most one transition, inside [first - tol, last + tol].
Recall is per truth type (did it find the boundary); precision is per claimed
label (cut or gradual), right only against a transition of that kind.
"""
from __future__ import annotations

import json

from harness import knobs, reasons
from harness.checks.base import CheckResult

KINDS = ("cut", "dissolve", "fade")
GRADUAL = ("dissolve", "fade")
#: Labels a detector may give, and the claim each one makes; no label is a cut claim.
LABELS = {"": "cut", "cut": "cut", "gradual": "gradual", "dissolve": "gradual", "fade": "gradual"}
#: Frames a detection may sit outside a transition and still find it.
TOLERANCE_FRAMES = 2
#: Boundary F1 a case passes at.
MIN_F1 = 0.9


def detections(record) -> list[tuple[int, str]]:
    """(frame, claim) per detection, in frame order; ValueError names a malformed record."""
    got = json.loads(record) if isinstance(record, str) else record
    out = []
    for item in (got or {}).get("transitions") or []:
        at, label = item.get("at"), str(item.get("kind") or "").lower()
        if not isinstance(at, int) or isinstance(at, bool):
            raise ValueError(f"detection frame {at!r} is not an integer")
        if label not in LABELS:
            raise ValueError(f"unknown transition kind {label!r}; known: {', '.join(sorted(k for k in LABELS if k))}")
        out.append((at, LABELS[label]))
    return sorted(out)


def match(transitions, frames, tol: int) -> list[tuple[int, int]]:
    """(transition index, frame index) pairs: each window, by its end, takes the earliest free frame in it."""
    order = sorted(range(len(transitions)), key=lambda i: (transitions[i]["last"], transitions[i]["first"]))
    free = sorted(range(len(frames)), key=lambda j: frames[j])
    pairs = []
    for i in order:
        lo, hi = transitions[i]["first"] - tol, transitions[i]["last"] + tol
        j = next((j for j in free if lo <= frames[j] <= hi), None)
        if j is not None:
            free.remove(j)
            pairs.append((i, j))
    return sorted(pairs)


def _ratio(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def metrics(truth: dict, found: list[tuple[int, str]], tol: int) -> dict:
    """Counts and ratios for one clip; a ratio appears only where its denominator can be nonzero."""
    transitions, negatives = truth.get("transitions") or [], truth.get("negatives") or []
    frames = [at for at, _ in found]
    pairs = match(transitions, frames, tol)
    of = {j: transitions[i]["kind"] for i, j in pairs}
    out: dict = {}
    for kind in KINDS:
        total = sum(t["kind"] == kind for t in transitions)
        if total:
            hit = sum(transitions[i]["kind"] == kind for i, _ in pairs)
            out.update({f"shots_{kind}_found": hit, f"shots_{kind}_total": total,
                        f"shots_{kind}_recall": _ratio(hit, total)})
    for claim, kinds in (("cut", ("cut",)), ("gradual", GRADUAL)):
        claimed = [j for j, (_, c) in enumerate(found) if c == claim]
        if claimed:
            right = sum(of.get(j) in kinds for j in claimed)
            out.update({f"shots_{claim}_claimed": len(claimed), f"shots_{claim}_right": right,
                        f"shots_{claim}_precision": _ratio(right, len(claimed))})
    tp, fp, fn = len(pairs), len(found) - len(pairs), len(transitions) - len(pairs)
    out.update({"shots_2tp": 2 * tp, "shots_f1_den": 2 * tp + fp + fn,
                "shots_boundary_f1": _ratio(2 * tp, 2 * tp + fp + fn) if found or transitions else 1.0,
                "shots_false": fp})
    if negatives:
        spare = [frames[j] for j in range(len(frames)) if j not in of]
        hit = sum(any(n["first"] - tol <= at <= n["last"] + tol for at in spare) for n in negatives)
        out.update({"shots_negatives_hit": hit, "shots_negatives_total": len(negatives),
                    "shots_negatives_triggered": _ratio(hit, len(negatives))})
    return out


def check(record, truth: dict, tol: int | None = None, min_f1: float | None = None) -> CheckResult:
    """One clip's verdict: passes at boundary F1 of at least MIN_F1; a refused record is a backend fault."""
    try:
        got = json.loads(record) if isinstance(record, str) else (record or {})
    except ValueError:
        return CheckResult(False, "detector record is not JSON")
    if isinstance(got, dict) and got.get("refused"):
        agree = got.get("agreement") or {}
        over = agree.get("bound") is not None and agree.get("max_prob_diff", 0) > agree["bound"]
        return CheckResult(False, f"refused: {got['refused']}", failure_class=reasons.BACKEND_FAULT,
                           limit=knobs.limit("shots_mps_max_prob_diff", agree["bound"], "share") if over else "")
    try:
        found = detections(got)
    except (ValueError, AttributeError, TypeError) as exc:
        return CheckResult(False, f"malformed detector record: {exc}")
    tol = TOLERANCE_FRAMES if tol is None else tol
    bar = MIN_F1 if min_f1 is None else min_f1
    m = metrics(truth, found, tol)
    out = CheckResult(m["shots_boundary_f1"] >= bar)
    out.metrics = m
    if not out.ok:
        # A miss a doubled window would have found is the tolerance binding; otherwise the F1 bar is.
        near = metrics(truth, found, 2 * tol)["shots_2tp"] > m["shots_2tp"]
        out.limit = (knobs.limit("shots_tolerance_frames", tol, "frames") if near
                     else knobs.limit("shots_min_f1", bar, "share"))
        parts =[f"{k} {m[f'shots_{k}_found']}/{m[f'shots_{k}_total']}" for k in KINDS if f"shots_{k}_total" in m]
        out.reason = (f"boundary F1 {m['shots_boundary_f1']:.2f} under {bar}: "
                      f"{', '.join(parts + [str(m['shots_false']) + ' false'])}")
    return out
