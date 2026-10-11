"""Compare two runs that differ on one axis, cell by cell.

`evals.core.comparable()` refuses to rank runs whose receipts differ, and that
is right for a leaderboard: two sampling settings are two exams. A sensitivity
sweep asks the opposite question deliberately -- what does this axis DO? -- so
it needs a named exception rather than a bypass, and the exception has to be
narrow. `--across sampling` still refuses if the runs also differ on the case
set, the tier, the accelerator or anything else.

The comparison is PAIRED because the alternative is not. Two runs over the same
cases are matched on the base case id and its repeat index, never on row position, so the question is how many cells
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

#: Failure classes that are our limit or a request that never reached a model: neither lost nor gained, counted apart. #693.
UNJUDGED = (reasons.TIMEOUT, reasons.STEP_CAP, reasons.CONTEXT_EXCEEDED) + reasons.NEVER_RAN
#: On a timeout axis the timeout is the verdict under test, so only harness failures stay unjudged.
UNJUDGED_ON_A_TIMEOUT_AXIS = reasons.NEVER_RAN

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
    #: Cells where either side failed on a class in UNJUDGED. #693.
    unjudged: int = 0
    #: 1+(r-1)*rho: correlated repeats of a case count as one case in p. #591, #690.
    deff: float = 1.0
    #: Why the two sides could not be paired; p is then 1.0 and the verdict says so.
    refused: str = ""

    @property
    def discordant(self) -> int:
        return self.lost + self.gained

    @property
    def p(self) -> float:
        if self.refused:
            return 1.0
        lost, gained = shrink(self.lost, self.gained, self.deff)
        return sign_test(min(lost, gained), lost + gained)

    @property
    def verdict(self) -> str:
        from harness import adopt
        if self.refused:
            return f"not paired: {self.refused}"
        if not self.discordant:
            return "identical"
        return "differs" if self.p <= adopt.ALPHA else "no evidence"


def shrink(lost: int, gained: int, deff: float) -> tuple[int, int]:
    """Discordant cells as independent cases: gains rounded down, losses up, so shrinking never helps the challenger."""
    if deff <= 1.0 + 1e-9:
        return lost, gained
    return math.ceil(lost / deff - 1e-9), int(gained / deff + 1e-9)


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


def repeat_index(case_id) -> int:
    tail = str(case_id or "").partition("#")[2]
    return int(tail) if tail.isdigit() else 1


def draws(rows: list[dict], candidate: str | None = None, unjudged=UNJUDGED) -> dict[str, list]:
    """base case id -> verdict per draw in repeat order, whatever order the rows came in; None is unjudged."""
    from harness import holdout
    got: dict[str, list] = {}
    for r in rows:
        if candidate is not None and r.get("candidate") != candidate:
            continue
        got.setdefault(holdout.base_id(r.get("case_id")), []).append(
            (repeat_index(r.get("case_id")), _verdict(r, unjudged)))
    return {k: [ok for _, ok in sorted(v, key=lambda d: d[0])] for k, v in got.items()}


def pair(before: list[dict], after: list[dict], candidate: str | None = None, *,
         same_repeat: bool = False, name: str = "", unjudged=UNJUDGED) -> Cell:
    """One candidate across two runs, paired on base case and repeat index; refuses unequal case sets (or draws, with same_repeat). #690."""
    from harness import power
    a, b = draws(before, candidate, unjudged), draws(after, candidate, unjudged)
    label = name or candidate or ""
    if not a.keys() & b.keys():
        return Cell(label, 0, 0, 0, refused="the two runs share no case")
    if a.keys() != b.keys():
        return Cell(label, 0, 0, 0, refused=(
            f"the case sets differ: {len(a.keys() - b.keys())} only before, "
            f"{len(b.keys() - a.keys())} only after"))
    if same_repeat and any(len(a[k]) != len(b[k]) for k in a):
        ra = {len(v) for v in a.values()}
        rb = {len(v) for v in b.values()}
        return Cell(label, 0, 0, 0, refused=(
            f"the repeat differs: {'/'.join(map(str, sorted(ra)))} draws per case before, "
            f"{'/'.join(map(str, sorted(rb)))} after"))
    lost = gained = same = off = 0
    used = {}
    for k in a:
        judged = []
        for x, y in zip(a[k], b[k]):
            if x is None or y is None:
                off += 1
                continue
            judged.append((x, y))
            lost += x and not y
            gained += y and not x
            same += x == y
        if judged:
            used[k] = judged
    if not used:
        return Cell(label, lost, gained, same, off)
    rho = power.icc([[[x for x, _ in d] for d in used.values()], [[y for _, y in d] for d in used.values()]])
    repeat = sum(len(d) for d in used.values()) / len(used)
    deff = power.design_effect(repeat, power.DEFAULT_RHO if rho is None else rho)
    return Cell(label, lost, gained, same, off, deff=deff)


def _cell(candidate: str, a: dict, b: dict) -> Cell:
    keys = a.keys() & b.keys()
    off = {k for k in keys if a[k] is None or b[k] is None}
    keys -= off
    lost = sum(1 for k in keys if a[k] > b[k])
    gained = sum(1 for k in keys if b[k] > a[k])
    return Cell(candidate, lost, gained, len(keys) - lost - gained, len(off))


def cells(before: list[dict], after: list[dict], unjudged=UNJUDGED) -> list[Cell]:
    """Per candidate, how many cells changed verdict and which way; a timeout axis passes unjudged=()."""
    shared = ({r.get("candidate") for r in before}
              & {r.get("candidate") for r in after})
    return [pair(before, after, c, unjudged=unjudged) for c in sorted(c for c in shared if c)]


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


def _score(row: dict, metric: str = ""):
    """A judged row's verdict, or its signed `metric` when one is named (missing ranks last); None is unjudged. #701."""
    got = _verdict(row)
    if got is None or not metric:
        return got
    from evals.core import direction_of
    value = (row.get("metrics") or {}).get(metric)
    if value is None:
        return float("-inf")
    return float(value) * (1 if direction_of(metric) == "higher" else -1)


def head_to_head(rows: list[dict], incumbent: str, challenger: str, metric: str = "") -> Cell:
    """Two candidates over the same cases in ONE run, paired by case.

    DIFFERENT PAIRING FROM cells(). That one matches a candidate against
    ITSELF across two runs, which is the sweep question: what did this axis
    do? This one matches two candidates against EACH OTHER on the same cases,
    which is the adoption question: is the challenger better here?

    Using cells() for this returns nothing at all, because the two runs it is
    handed share no candidate, and an empty result reads as "no difference"
    rather than "wrong comparison".
    """
    mine = {r.get("case_id"): _score(r, metric) for r in rows if r.get("candidate") == incumbent}
    theirs = {r.get("case_id"): _score(r, metric) for r in rows if r.get("candidate") == challenger}
    return _cell(challenger, mine, theirs)
