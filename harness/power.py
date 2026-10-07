"""How many repeats the paired adopt gate needs to see a real difference. #479.

The gate is the exact McNemar test (paired.sign_test) on cells matched by case
and repeat. Its power is computed from the incumbent's stored per-case pass
rates p_i and the lane's minimum meaningful difference d: the challenger
passes a cell of case i with q_i = min(1, p_i + d), cells independent. A null
from a gate with too little power is reported as underpowered, never as "no
better".
"""
from __future__ import annotations

import functools
import math
from dataclasses import asdict, dataclass

#: Power the gate must reach before a null may be read as "no better".
TARGET = 0.8
#: The most repeats the adopt command and the discover loop will spend.
CAP = 16
#: The smallest change in per-cell pass rate worth adopting for, per lane.
EFFECT = {}
DEFAULT_EFFECT = 0.2
#: Pass rate assumed for a case the incumbent has no stored rows for.
UNSEEN = 0.5


def effect_for(lane: str) -> float:
    return EFFECT.get((lane or "").strip().lower(), DEFAULT_EFFECT)


def _alpha() -> float:
    from harness import adopt
    return adopt.ALPHA


@functools.lru_cache(maxsize=None)
def _critical(d: int, alpha: float) -> int:
    """Fewest gains of d discordant cells that the two-sided test rejects on."""
    total = 2 ** d
    tail = 0
    for k in range(0, d // 2 + 1):
        tail += math.comb(d, k)
        if 2 * tail > alpha * total:
            return d - k + 1 if k else d + 1
    return d - d // 2


def power(rates, effect: float, repeat: int = 1, alpha: float | None = None) -> float:
    """P(the gate adopts) when the challenger is better by `effect` per cell."""
    alpha = _alpha() if alpha is None else alpha
    rates = list(rates)
    if not rates or repeat < 1:
        return 0.0
    n = len(rates) * repeat
    gain = sum((1 - p) * min(1.0, p + effect) for p in rates) / len(rates)
    lose = sum(p * (1 - min(1.0, p + effect)) for p in rates) / len(rates)
    disc = gain + lose
    if disc <= 0:
        return 0.0
    r = gain / disc
    out = 0.0
    for d in range(1, n + 1):
        need = _critical(d, alpha)
        if need > d:
            continue
        p_d = math.comb(n, d) * disc ** d * (1 - disc) ** (n - d)
        if p_d == 0:
            continue
        out += p_d * sum(math.comb(d, g) * r ** g * (1 - r) ** (d - g)
                         for g in range(need, d + 1))
    return min(1.0, out)


@dataclass(frozen=True)
class Plan:
    repeat: int
    power: float
    cells: int
    cases: int
    effect: float
    alpha: float
    target: float
    cap: int
    capped: bool
    stochastic: bool
    observed: int
    why: str

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def enough(self) -> bool:
        return self.power >= self.target


def plan(rates, effect: float | None = None, *, stochastic: bool = True,
         alpha: float | None = None, target: float = TARGET, cap: int = CAP,
         repeat: int | None = None, observed: int = 0) -> Plan:
    """The smallest repeat reaching `target`, or `repeat` if one was chosen."""
    alpha = _alpha() if alpha is None else alpha
    effect = DEFAULT_EFFECT if effect is None else effect
    rates = list(rates)
    k = len(rates)

    def at(r: int) -> float:
        return power(rates, effect, r, alpha)

    if not stochastic:
        got = at(1)
        why = ("" if got >= target else
               f"repeat adds no cells in this lane; {k} cases give power "
               f"{got:.2f}, so more cases are needed")
        return Plan(1, got, k, k, effect, alpha, target, cap, False, False,
                    observed, why)
    if repeat:
        got = at(repeat)
        return Plan(repeat, got, k * repeat, k, effect, alpha, target, cap,
                    False, True, observed,
                    "" if got >= target else f"chosen repeat {repeat} gives "
                    f"power {got:.2f}")
    for r in range(1, cap + 1):
        got = at(r)
        if got >= target:
            return Plan(r, got, k * r, k, effect, alpha, target, cap, False,
                        True, observed, "")
    return Plan(cap, got, k * cap, k, effect, alpha, target, cap, True, True,
                observed, f"capped at repeat {cap} with power {got:.2f}")


def incumbent_rates(conn, lane: str, key: str, case_ids) -> tuple[dict, int]:
    """case -> the incumbent's stored pass rate, and how many rows it rests on.

    A case with no rows takes the incumbent's pooled rate, else UNSEEN.
    """
    from harness import holdout
    rows = conn.execute(
        "SELECT x.case_id, x.passed FROM results x JOIN runs u ON u.id = x.run_id "
        "WHERE u.lane = ? AND u.tier = 'measure' AND x.candidate = ?",
        ((lane or "").strip().lower(), key)).fetchall()
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(holdout.base_id(r["case_id"]), []).append(int(r["passed"]))
    every = [v for vs in by.values() for v in vs]
    pooled = sum(every) / len(every) if every else UNSEEN
    out = {}
    for cid in case_ids:
        got = by.get(cid)
        out[cid] = sum(got) / len(got) if got else pooled
    return out, sum(len(by.get(c) or ()) for c in case_ids)
