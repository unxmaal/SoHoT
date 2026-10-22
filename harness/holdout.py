"""Per-lane dev/holdout split, and when a lane's holdout is saturated. #479.

Anything that adapts to failures (the screen, prompt or sampling tweaks, a
repair loop being tuned) sees only dev; the adopt gate decides on holdout and
reports dev beside it. A case's side comes from its content digest, so an
unchanged case keeps its side and an edited one is drawn again.
"""
from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass
from pathlib import Path

#: Bump when the assignment rule changes; recorded on every run and verdict.
VERSION = "1"
FRACTION = 0.3
MIN_HOLDOUT = 3
MIN_DEV = 3
#: An incumbent passing at least this share of holdout leaves nothing to separate.
SATURATED = 0.95
SIDES = ("all", "dev", "holdout")


@dataclass(frozen=True)
class Split:
    lane: str
    dev: tuple
    holdout: tuple
    too_small: bool
    version: str = VERSION

    def side(self, case_id: str) -> str:
        """'holdout', 'dev' or '' for a case id, with or without its #repeat."""
        base = base_id(case_id)
        if base in self.holdout:
            return "holdout"
        return "dev" if base in self.dev else ""

    @property
    def caveat(self) -> str:
        if not self.too_small:
            return ""
        return (f"the {self.lane} lane is too small to split "
                f"({len(self.holdout)} cases, needs "
                f"{MIN_HOLDOUT + MIN_DEV}), so it was decided on all cases")

    def as_dict(self) -> dict:
        return {"lane": self.lane, "version": self.version,
                "too_small": self.too_small, "dev": list(self.dev),
                "holdout": list(self.holdout)}


def base_id(case_id: str) -> str:
    return str(case_id or "").split("#", 1)[0]


def _draw(case) -> float:
    from evals.core import case_digest
    h = hashlib.sha256(f"{VERSION}\0{case_digest(case)}".encode("utf-8"))
    return int(h.hexdigest()[:12], 16) / 16 ** 12


def task_of(case) -> str:
    """The task a history case belongs to (params.fix), "" for a case that stands alone."""
    from evals.importers.history import VARIANTS
    params = getattr(case, "params", None) or {}
    return str(params["fix"]) if params.get("fix") and params.get("variant") in (*VARIANTS, "request") else ""


def version(lane: str) -> str:
    """The assignment version a lane's split records: a task-split lane adds the frozen task seed. #995."""
    from evals.importers import history
    return f"{VERSION}+tasks-{history.SPLIT_SEED}" if (lane or "").strip().lower() == history.LANE else VERSION


def _assign_tasks(lane: str, cases) -> Split:
    """A task's variants share one side, frozen by the manifest's seed; a lone case draws as any other. #995."""
    from evals.importers import history
    sides = {c.id: (history.side_of(task_of(c)) if task_of(c) else
                    "holdout" if _draw(c) < FRACTION else "dev") for c in cases}
    hold = tuple(sorted(k for k, v in sides.items() if v == "holdout"))
    dev = tuple(sorted(k for k, v in sides.items() if v == "dev"))
    if len(hold) < MIN_HOLDOUT or len(dev) < MIN_DEV:
        every = tuple(sorted(sides))
        return Split(lane, every, every, True, version(lane))
    return Split(lane, dev, hold, False, version(lane))


def assign(lane: str, cases) -> Split:
    """Holdout is every case drawing under FRACTION, floored at MIN_HOLDOUT; history tasks split whole."""
    cases = list(cases)
    if any(task_of(c) for c in cases):
        return _assign_tasks(lane, cases)
    drawn = sorted(((_draw(c), c.id) for c in cases), key=lambda t: (t[0], t[1]))
    ids = [cid for _, cid in drawn]
    if len(ids) < MIN_HOLDOUT + MIN_DEV:
        return Split(lane, tuple(sorted(ids)), tuple(sorted(ids)), True)
    n = sum(1 for d, _ in drawn if d < FRACTION)
    n = min(max(n, MIN_HOLDOUT), len(ids) - MIN_DEV)
    return Split(lane, tuple(sorted(ids[n:])), tuple(sorted(ids[:n])), False)


@functools.lru_cache(maxsize=8)
def _cases(root: str, private: bool, stamp: tuple) -> tuple:
    # Per root, so a new local root does not reload every shipped case. #720.
    from evals.core import load_cases
    return tuple(load_cases(root, private=True) if private else load_cases(root))


def _stamp(root: Path) -> tuple:
    return tuple(sorted((str(p), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()))


@functools.lru_cache(maxsize=8)
def _splits(roots: tuple) -> dict:
    by: dict[str, list] = {}
    for root, private, stamp in roots:
        for c in _cases(root, private, stamp):
            by.setdefault(c.modality, []).append(c)
    return {lane: assign(lane, cases) for lane, cases in by.items()}


def splits(root=None) -> dict:
    """lane -> the split of its shipped cases (evals/cases by default) plus local-only ones. #654."""
    from evals.core import local_root
    roots = [(Path(root) if root is not None else
              Path(__file__).resolve().parent.parent / "evals" / "cases", False)]
    if root is None and local_root().is_dir():
        roots.append((local_root(), True))
    # Keyed on every file's mtime, so an edited case is drawn again.
    return _splits(tuple((str(r), private, _stamp(r)) for r, private in roots))


def for_lane(lane: str, root=None) -> Split:
    """The split of a lane's shipped cases (evals/cases by default)."""
    key = (lane or "").strip().lower()
    return splits(root).get(key) or Split(key, (), (), True)


def only(cases, side: str):
    """The cases on one side, splitting each lane among `cases` on its own."""
    if side == "all":
        return cases
    if side not in SIDES:
        raise ValueError(f"unknown split {side!r}; known: {', '.join(SIDES)}")
    by: dict[str, list] = {}
    for c in cases:
        by.setdefault(c.modality, []).append(c)
    keep = set()
    for lane, mine in by.items():
        keep |= set(getattr(assign(lane, mine), side))
    return [c for c in cases if c.id in keep]


def rows_on(rows, split: Split, side: str) -> list[dict]:
    return [r for r in rows or [] if split.side(r.get("case_id")) == side]


def saturated(holdout_pass_rate) -> bool:
    return holdout_pass_rate is not None and holdout_pass_rate >= SATURATED
