"""Compare two runs that differ on one axis, cell by cell.

`evals.core.comparable()` refuses to rank runs whose receipts differ, and that
is right for a leaderboard: two sampling settings are two exams. A sensitivity
sweep asks the opposite question deliberately -- what does this axis DO? -- so
it needs a named exception rather than a bypass, and the exception has to be
narrow. `--across sampling` still refuses if the runs also differ on the case
set, the tier, the accelerator or anything else.

The comparison is PAIRED because the alternative is not. Two runs over the same
cases are matched on case and repeat index, so the question is how many cells
changed verdict and in which direction, not whether two rates differ. A rate
hides which cases moved: issue #90's code lane held 15/27 across two
temperatures with an identical passing set at one pair and two cells swapped at
another, and only the paired view separates those.

SIGNIFICANCE IS THE EXACT McNEMAR TEST, which on discordant pairs alone is a
two-sided binomial sign test at p=0.5. Concordant cells carry no information
about a change and are excluded by construction. The point is to stop a visible
trend being reported as an effect: 12/27 falling to 9/27 is 5 lost against 2
gained, which is p=0.45 and no evidence of anything.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from harness import reasons

#: Failure classes that are our limit, not a verdict: neither lost nor gained, counted apart. #693.
UNJUDGED = (reasons.TIMEOUT,)

#: Receipt fields a sweep may deliberately vary, one at a time.
AXES = ("sampling", "repeat", "accelerator", "instruments", "where", "gateway", "launch",
        "max_tokens", "budget_ladder", "machine", "served")


@dataclass(frozen=True)
class Cell:
    """One candidate's before/after on one axis."""
    candidate: str
    lost: int
    gained: int
    unchanged: int
    #: Cells where either side hit a limit in UNJUDGED. #693.
    unjudged: int = 0

    @property
    def discordant(self) -> int:
        return self.lost + self.gained

    @property
    def p(self) -> float:
        return sign_test(min(self.lost, self.gained), self.discordant)

    @property
    def verdict(self) -> str:
        if not self.discordant:
            return "identical"
        return "differs" if self.p <= 0.05 else "no evidence"


def sign_test(k: int, n: int) -> float:
    """Two-sided exact binomial at p=0.5, the McNemar test on discordant pairs.

    n=0 is 1.0 rather than undefined: no cell changed, so there is nothing to
    reject. Returning 0.0 there would call two identical runs different.
    """
    if n <= 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def _verdict(row: dict, unjudged=UNJUDGED):
    """True or False for a judged row; None for a failure on a limit in `unjudged`."""
    if not row.get("passed") and row.get("failure_class") in unjudged:
        return None
    return bool(row.get("passed"))


def _verdicts(rows: list[dict], candidate: str, unjudged=UNJUDGED) -> dict:
    """Pass/fail per cell. The repeat index is part of the key, so three
    repetitions of one case are three cells rather than one averaged."""
    out = {}
    for i, row in enumerate(rows):
        if row.get("candidate") != candidate:
            continue
        out[f"{row.get('case_id')}#{i}"] = _verdict(row, unjudged)
    return out


def _cell(candidate: str, a: dict, b: dict) -> Cell:
    keys = a.keys() & b.keys()
    off = {k for k in keys if a[k] is None or b[k] is None}
    keys -= off
    lost = sum(1 for k in keys if a[k] and not b[k])
    gained = sum(1 for k in keys if not a[k] and b[k])
    return Cell(candidate, lost, gained, len(keys) - lost - gained, len(off))


def cells(before: list[dict], after: list[dict], unjudged=UNJUDGED) -> list[Cell]:
    """Per candidate, how many cells changed verdict and which way; a timeout axis passes unjudged=()."""
    shared = ({r.get("candidate") for r in before}
              & {r.get("candidate") for r in after})
    return [_cell(c, _verdicts(before, c, unjudged), _verdicts(after, c, unjudged))
            for c in sorted(c for c in shared if c)]


def differences(before, after) -> list[str]:
    """Receipt fields on which two runs disagree. The axis under test is
    expected here; a SECOND entry means the sweep is confounded. Each exam
    knob is its own axis, `knobs.<name>`. #636."""
    out = []
    for name in AXES:
        if getattr(before, name, None) != getattr(after, name, None):
            out.append(name)
    a, b = getattr(before, "knobs", None) or {}, getattr(after, "knobs", None) or {}
    out += [f"knobs.{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    return out


def is_axis(axis: str) -> bool:
    """A receipt field a sweep may vary, or one registered exam knob."""
    from harness import knobs
    name = axis[len("knobs."):] if axis.startswith("knobs.") else ""
    return axis in AXES or (name in knobs.KNOBS and knobs.KNOBS[name].receipt == "knobs")


def value(receipt, axis: str):
    """What a receipt records for an axis."""
    if axis.startswith("knobs."):
        return (getattr(receipt, "knobs", None) or {}).get(axis[len("knobs."):])
    return getattr(receipt, axis, None)


def head_to_head(rows: list[dict], incumbent: str, challenger: str) -> Cell:
    """Two candidates over the same cases in ONE run, paired by case.

    DIFFERENT PAIRING FROM cells(). That one matches a candidate against
    ITSELF across two runs, which is the sweep question: what did this axis
    do? This one matches two candidates against EACH OTHER on the same cases,
    which is the adoption question: is the challenger better here?

    Using cells() for this returns nothing at all, because the two runs it is
    handed share no candidate, and an empty result reads as "no difference"
    rather than "wrong comparison".
    """
    mine = {r.get("case_id"): _verdict(r) for r in rows if r.get("candidate") == incumbent}
    theirs = {r.get("case_id"): _verdict(r) for r in rows if r.get("candidate") == challenger}
    return _cell(challenger, mine, theirs)
