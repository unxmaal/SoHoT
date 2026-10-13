"""Interim looks at a paused paired run: success only with alpha spent across looks, futility only past a declared bound. #813."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist

#: Futility stops a run only when conditional power under the plan's effect falls below this AND the challenger is not ahead.
FUTILITY_CP = 0.10


def spent(t: float, alpha: float) -> float:
    """Alpha an O'Brien-Fleming (Lan-DeMets) spending function has used by information fraction t."""
    if t <= 0:
        return 0.0
    t = min(1.0, t)
    z = NormalDist().inv_cdf(1 - alpha / 2)
    return min(alpha, 2 * (1 - NormalDist().cdf(z / math.sqrt(t))))


def conditional_power(gained: int, lost: int, remaining: int, gain: float, lose: float,
                      alpha: float) -> float:
    """P(the final sign test adopts) if the remaining cells go at per-cell odds (gain, lose)."""
    from harness import power
    disc = gain + lose
    if remaining <= 0 or disc <= 0:
        return 1.0 if _wins(gained, lost, alpha) else 0.0
    r = gain / disc
    total = 0.0
    for m in range(remaining + 1):
        pm = power._pmf(remaining, m, disc)
        if pm < 1e-12:
            continue
        total += pm * sum(power._pmf(m, k, r) for k in range(m + 1)
                          if _wins(gained + k, lost + m - k, alpha))
    return min(1.0, total)


def _wins(gained: int, lost: int, alpha: float) -> bool:
    from harness import power
    return gained > lost and gained >= power._critical(gained + lost, alpha)


@dataclass(frozen=True)
class Look:
    n: int
    t: float
    gained: int
    lost: int
    nominal: float
    spent: float
    cp: float
    decision: str
    text: str

    def as_dict(self) -> dict:
        return asdict(self)


def look(rows, *, lane: str, inc_key: str, ch_key: str, split, plan: dict, alpha: float,
         spent_before: float, n: int, spec: str = "", tested: int = 0):
    """One look: (Look, the adopt.Verdict when it stops for success or futility, else None)."""
    from harness import adopt, holdout, paired
    got = holdout.rows_on(rows, split, "holdout")
    cell, _, _ = adopt.paired_p(got, inc_key, ch_key, lane)
    done = cell.gained + cell.lost + cell.unchanged
    planned = max(1, len(split.holdout) * int(plan.get("repeat") or 1))
    t = min(1.0, done / planned)
    used = spent(t, alpha)
    nominal = max(0.0, used - spent_before)
    deff = _deff(plan)
    lost, gained = paired.shrink(cell.lost, cell.gained, deff)
    gain, lose = plan.get("odds") or (0.0, 0.0)
    cp = conditional_power(gained, lost, int((planned - done) / deff), gain, lose, alpha)
    head = (f"look {n} at {done}/{planned} holdout cells: {cell.gained} gained, {cell.lost} lost, "
            f"conditional power {cp:.2f}, alpha {nominal:.4f} of {alpha:.4f} spendable here")
    if done and nominal > 0:
        v = adopt.decide(lane, {"candidate": inc_key}, {"candidate": ch_key}, rows, split=split,
                         spec=spec, tested=tested, alpha=nominal)
        if v.adopt:
            return Look(n, t, cell.gained, cell.lost, nominal, used, cp, "success",
                        f"{head}; stopped for success"), v
    if done and cp < FUTILITY_CP and cell.gained <= cell.lost:
        v = adopt.Verdict(lane, inc_key, ch_key, False,
                          f"futility: {head}; under the plan's +{plan.get('effect', 0):.2f} the "
                          f"challenger reaches the gate with probability {cp:.2f} < {FUTILITY_CP}")
        return Look(n, t, cell.gained, cell.lost, nominal, used, cp, "futility",
                    f"{head}; stopped for futility"), v
    return Look(n, t, cell.gained, cell.lost, nominal, used, cp, "continue", f"{head}; continues"), None


def _deff(plan: dict) -> float:
    cells, cases, repeat = plan.get("cells"), plan.get("cases"), plan.get("repeat") or 1
    if not cells or not cases:
        return 1.0
    return max(1.0, cases * repeat / cells)
