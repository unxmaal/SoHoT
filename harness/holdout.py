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


def assign(lane: str, cases) -> Split:
    """Holdout is every case drawing under FRACTION, floored at MIN_HOLDOUT."""
    drawn = sorted(((_draw(c), c.id) for c in cases), key=lambda t: (t[0], t[1]))
    ids = [cid for _, cid in drawn]
    if len(ids) < MIN_HOLDOUT + MIN_DEV:
        return Split(lane, tuple(sorted(ids)), tuple(sorted(ids)), True)
    n = sum(1 for d, _ in drawn if d < FRACTION)
    n = min(max(n, MIN_HOLDOUT), len(ids) - MIN_DEV)
    return Split(lane, tuple(sorted(ids[n:])), tuple(sorted(ids[:n])), False)


@functools.lru_cache(maxsize=8)
def _splits(root: str, stamp: tuple) -> dict:
    from evals.core import load_cases
    by: dict[str, list] = {}
    for c in load_cases(root):
        by.setdefault(c.modality, []).append(c)
    return {lane: assign(lane, cases) for lane, cases in by.items()}


def for_lane(lane: str, root=None) -> Split:
    """The split of a lane's shipped cases (evals/cases by default)."""
    root = Path(root) if root is not None else (
        Path(__file__).resolve().parent.parent / "evals" / "cases")
    # Keyed on every file's mtime, so an edited case is drawn again.
    stamp = tuple(sorted((str(p), p.stat().st_mtime_ns)
                         for p in root.rglob("*") if p.is_file()))
    key = (lane or "").strip().lower()
    return _splits(str(root), stamp).get(key) or Split(key, (), (), True)


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
