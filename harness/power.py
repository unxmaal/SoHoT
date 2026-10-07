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
import statistics
from dataclasses import asdict, dataclass, replace

#: Power the gate must reach before a null may be read as "no better".
TARGET = 0.8
#: The most repeats the adopt command and the discover loop will spend.
CAP = 16
#: The smallest change in per-cell pass rate worth adopting for, per lane.
EFFECT = {}
DEFAULT_EFFECT = 0.2
#: Pass rate assumed for a case the incumbent has no stored rows for.
UNSEEN = 0.5
#: Within-case correlation assumed until a repeated case measures it. #591.
DEFAULT_RHO = 1.0
#: The largest holdout cases_needed searches.
MAX_CASES = 2000
#: Minutes the loop may spend on one challenger's paired run. #591.
BUDGET_MIN = 120.0
#: The repeat run when the powered one does not fit the budget.
FALLBACK_REPEAT = 3
#: A stochastic lane whose correlation is unmeasured runs at least this, so the run measures it.
MEASURING_REPEAT = 2
#: Repeats past the one reaching this share of the best power buy nothing.
PLATEAU = 0.95
#: Or within this much of it.
PLATEAU_ABS = 0.01


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


def effective_cells(cases: int, repeat: int, rho: float) -> int:
    """Cells worth of independent evidence: k*r shrunk by the design effect 1+(r-1)*rho."""
    if cases < 1 or repeat < 1:
        return 0
    return int(cases * repeat / design_effect(repeat, rho) + 1e-9)


def design_effect(repeat: float, rho: float) -> float:
    return 1.0 + max(0.0, repeat - 1) * min(1.0, max(0.0, rho))


def _pmf(n: int, k: int, p: float) -> float:
    if k < 0 or k > n:
        return 0.0
    if p == 0.0:
        return 1.0 if k == 0 else 0.0
    if p == 1.0:
        return 1.0 if k == n else 0.0
    log_c = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return math.exp(log_c + k * math.log(p) + (n - k) * math.log(1.0 - p))


@functools.lru_cache(maxsize=4096)
def power_cells(gain: float, lose: float, n: int, alpha: float) -> float:
    """Power of the two-sided exact sign test over n independent paired cells."""
    disc = gain + lose
    if n < 1 or disc <= 0 or gain <= 0:
        return 0.0
    r = gain / disc
    mean = n * disc
    sd = math.sqrt(n * disc * (1.0 - disc))
    lo = max(1, math.floor(mean - 12.0 * sd) - 1)
    hi = min(n, math.ceil(mean + 12.0 * sd) + 1)
    total = 0.0
    for d in range(lo, hi + 1):
        need = _critical(d, alpha)
        if need > d:
            continue
        total += _pmf(n, d, disc) * sum(_pmf(d, j, r) for j in range(need, d + 1))
    return min(1.0, total)


def _cell_odds(rates, effect: float) -> tuple[float, float]:
    """Per-cell P(gained) and P(lost) when the challenger is better by `effect`."""
    rates = list(rates)
    gain = sum((1 - p) * min(1.0, p + effect) for p in rates) / len(rates)
    lose = sum(p * (1 - min(1.0, p + effect)) for p in rates) / len(rates)
    return gain, lose


def power(rates, effect: float, repeat: int = 1, alpha: float | None = None,
          rho: float = 0.0) -> float:
    """P(the gate adopts) when the challenger is better by `effect` per cell.

    `rho` is the within-case correlation of repeats: at 1 a case repeated r
    times is one case, at 0 it is r independent cells. #591.
    """
    alpha = _alpha() if alpha is None else alpha
    rates = list(rates)
    if not rates or repeat < 1:
        return 0.0
    gain, lose = _cell_odds(rates, effect)
    return power_cells(gain, lose, effective_cells(len(rates), repeat, rho), alpha)


def cases_needed(rates, effect: float, *, rho: float, stochastic: bool = True,
                 alpha: float | None = None, target: float = TARGET,
                 cap: int = CAP, most: int | None = None) -> int | None:
    """The smallest holdout, at least today's, reaching `target` at some repeat up to `cap`.

    New cases are assumed to look like today's holdout. None when the incumbent
    leaves nothing to gain or no holdout up to `most` cases reaches the target.
    """
    alpha = _alpha() if alpha is None else alpha
    rates = list(rates)
    if not rates:
        return None
    gain, lose = _cell_odds(rates, effect)
    if gain <= 0:
        return None
    repeats = range(1, cap + 1) if stochastic else (1,)
    for k in range(len(rates), (most or MAX_CASES) + 1):
        cells = {effective_cells(k, r, rho) for r in repeats}
        if any(power_cells(gain, lose, n, alpha) >= target for n in cells):
            return k
    return None


def icc(by_candidate) -> float | None:
    """Within-case correlation of pass/fail draws, one-way ANOVA, each candidate centred on its own mean.

    `by_candidate` is a list, per candidate, of groups of draws of one case.
    None when no case was drawn twice or nothing varies.
    """
    groups_seen = 0
    draws = 0
    ssb = ssw = 0.0
    dfb = dfw = 0
    for cand in by_candidate:
        groups = [list(g) for g in cand if len(g)]
        if not groups:
            continue
        every = [y for g in groups for y in g]
        centre = sum(every) / len(every)
        for g in groups:
            mean_g = sum(g) / len(g)
            ssb += len(g) * (mean_g - centre) ** 2
            ssw += sum((y - mean_g) ** 2 for y in g)
            dfw += len(g) - 1
            groups_seen += 1
            draws += len(g)
        dfb += len(groups) - 1
    if dfb <= 0 or dfw <= 0:
        return None
    msb, msw = ssb / dfb, ssw / dfw
    denom = msb + (draws / groups_seen - 1) * msw
    if denom == 0:
        return None
    return max(0.0, min(1.0, (msb - msw) / denom))


def rows_icc(rows, names) -> tuple[float | None, float]:
    """(rho, mean draws per case) over result rows of the named candidates."""
    from harness import holdout
    by: dict[str, dict[str, list[int]]] = {n: {} for n in names}
    for r in rows or ():
        mine = by.get(r.get("candidate"))
        if mine is not None:
            mine.setdefault(holdout.base_id(r.get("case_id")), []).append(
                int(bool(r.get("passed"))))
    groups = [g for cases in by.values() for g in cases.values()]
    repeat = sum(map(len, groups)) / len(groups) if groups else 1.0
    return icc([list(cases.values()) for cases in by.values()]), repeat


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
    rho: float = 0.0
    rho_measured: bool = False
    cases_needed: int | None = None
    needed_repeat: int | None = None
    projected_s: float | None = None
    budget_s: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def enough(self) -> bool:
        return self.power >= self.target


def plan(rates, effect: float | None = None, *, stochastic: bool = True,
         alpha: float | None = None, target: float = TARGET, cap: int = CAP,
         repeat: int | None = None, observed: int = 0,
         rho: float | None = None) -> Plan:
    """The smallest repeat reaching `target`, or `repeat` if one was chosen.

    `rho` is the incumbent's measured within-case correlation; None assumes
    DEFAULT_RHO, so an unmeasured lane is never credited with independent
    repeats. When no repeat reaches the target the plan says how many holdout
    cases would. #591.
    """
    alpha = _alpha() if alpha is None else alpha
    effect = DEFAULT_EFFECT if effect is None else effect
    rates = list(rates)
    k = len(rates)
    measured = rho is not None
    rho = DEFAULT_RHO if rho is None else rho
    need = cases_needed(rates, effect, rho=rho, stochastic=stochastic,
                        alpha=alpha, target=target, cap=cap)
    extra = {"rho": rho, "rho_measured": measured, "cases_needed": need}

    def at(r: int) -> float:
        return power(rates, effect, r, alpha, rho)

    def made(r, got, capped, why):
        return Plan(r, got, effective_cells(k, r, rho), k, effect, alpha, target,
                    cap, capped, stochastic, observed, why, **extra)

    more = _more_cases(rates, effect, k, need, target)
    if not stochastic:
        got = at(1)
        return made(1, got, False, "" if got >= target else
                    f"repeat adds no cells in this lane; {k} cases give power "
                    f"{got:.2f}, so more cases are needed: {more}")
    if repeat:
        got = at(repeat)
        return made(repeat, got, False, "" if got >= target else
                    f"chosen repeat {repeat} gives power {got:.2f}; {more}")
    powers = [at(r) for r in range(1, cap + 1)]
    for r, got in enumerate(powers, 1):
        if got >= target:
            return made(r, got, False, "")
    best = max(powers)
    r = next(i for i, got in enumerate(powers, 1)
             if got >= best * PLATEAU or best - got <= PLATEAU_ABS)
    if not measured:
        r = max(r, min(MEASURING_REPEAT, cap))
    if r < cap and rho > 0:
        why = (f"repeats of a case are correlated (rho {rho:.2f}"
               f"{'' if measured else ', assumed until measured'}), so no repeat "
               f"up to {cap} reaches {target}: power {best:.2f} at most, already "
               f"at repeat {r}; {more}")
        return made(r, powers[r - 1], False, why)
    return made(cap, powers[-1], True,
                f"capped at repeat {cap} with power {powers[-1]:.2f}; {more}")


def _more_cases(rates, effect, k: int, need: int | None, target: float) -> str:
    if need is None:
        if not rates or _cell_odds(rates, effect)[0] <= 0:
            return ("the holdout is saturated: the incumbent passes every case, "
                    "so no number of cases can show a gain")
        return f"no holdout of up to {MAX_CASES} cases reaches {target}"
    if need <= k:
        return f"{k} holdout cases are enough"
    from harness import holdout
    return (f"{need} holdout cases would reach {target}: {need - k} more holdout "
            f"cases, about {math.ceil((need - k) / holdout.FRACTION)} more lane "
            f"cases at the {holdout.FRACTION} holdout fraction")


def projected_seconds(cases: int, repeat: int, median_s: float | None,
                      candidates: int = 2) -> float | None:
    """Wall time of a paired run: every lane case, every repeat, both candidates."""
    if median_s is None:
        return None
    return cases * repeat * candidates * median_s


def _hm(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{max(m, 1)}m"


def within_budget(chosen: Plan, rates, *, cases_run: int, median_s: float | None,
                  budget_s: float, explicit: bool = False) -> Plan:
    """The planned repeat if its projected time fits `budget_s`, else the fallback and what power would cost. #591."""
    def cost(r):
        return projected_seconds(cases_run, r, median_s)

    if explicit or not chosen.stochastic:
        return replace(chosen, projected_s=cost(chosen.repeat), budget_s=budget_s,
                       needed_repeat=chosen.repeat)
    if median_s is None:
        r = min(chosen.repeat, FALLBACK_REPEAT)
        note = (f"no measured seconds per case in this lane, so the cost of "
                f"repeat {chosen.repeat} is unknown; ran repeat {r}")
    elif cost(chosen.repeat) <= budget_s:
        return replace(chosen, projected_s=cost(chosen.repeat), budget_s=budget_s,
                       needed_repeat=chosen.repeat)
    else:
        r = max(1, min(FALLBACK_REPEAT, chosen.repeat, int(budget_s // cost(1))))
        note = (f"repeat {chosen.repeat} for power {chosen.power:.2f} would take "
                f"{_hm(cost(chosen.repeat))}, over the {_hm(budget_s)} budget; "
                f"ran repeat {r}")
    got = plan(rates, chosen.effect, stochastic=True, alpha=chosen.alpha,
               target=chosen.target, cap=chosen.cap, repeat=r,
               observed=chosen.observed,
               rho=chosen.rho if chosen.rho_measured else None)
    return replace(got, needed_repeat=chosen.repeat, projected_s=cost(r),
                   budget_s=budget_s,
                   why="; ".join(x for x in (note, got.why) if x))


def draws_from(rows, key: str) -> tuple[dict[str, list[int]], float | None]:
    """case -> one candidate's pass/fail draws, and its median seconds per case."""
    from harness import holdout
    by: dict[str, list[int]] = {}
    secs = []
    for r in rows:
        if r["candidate"] != key:
            continue
        by.setdefault(holdout.base_id(r["case_id"]), []).append(int(bool(r["passed"])))
        if r["seconds"] is not None:
            secs.append(float(r["seconds"]))
    return by, (statistics.median(secs) if secs else None)


def incumbent_profile(conn, lane: str, key: str) -> tuple[dict[str, list[int]], float | None]:
    """The incumbent's stored draws per case in this lane's measure runs, and its median seconds."""
    rows = conn.execute(
        "SELECT x.case_id, x.passed, x.seconds, x.candidate FROM results x "
        "JOIN runs u ON u.id = x.run_id "
        "WHERE u.lane = ? AND u.tier = 'measure' AND x.candidate = ?",
        ((lane or "").strip().lower(), key)).fetchall()
    return draws_from(rows, key)


def control_of(receipts, prefer=()) -> str:
    """The candidate a set of receipts shares: a preferred name, else the one in most receipts."""
    seen: dict[str, list[int]] = {}
    for rows in receipts:
        for name in {r.get("candidate") for r in rows}:
            got = seen.setdefault(name, [0, 0])
            got[0] += 1
            got[1] += sum(1 for r in rows if r.get("candidate") == name)
    for name in prefer:
        if name in seen:
            return name
    return max(sorted(seen), key=lambda n: tuple(seen[n]), default="")


def stratified(values: list[float], n: int) -> list[float]:
    """n deterministic draws following the empirical distribution of `values`."""
    if n == 0:
        return []
    ordered = sorted(values)
    return [ordered[int((j + 0.5) * len(ordered) / n)] for j in range(n)]


def unmeasured(draws: dict, case_ids) -> list:
    """The cases with no draws: their rates in rates_from are projected, not measured. #608."""
    return [c for c in case_ids if not draws.get(c)]


def rates_from(draws: dict, case_ids) -> tuple[dict, int]:
    """case -> pass rate; unseen cases drawn from the measured per-case rates (#608), else UNSEEN.

    A pooled rate would give every unseen case room to gain, but measured rates
    are bimodal: a case at 1.0 has none.
    """
    measured = [sum(v) / len(v) for v in draws.values() if v]
    out = {cid: sum(draws[cid]) / len(draws[cid]) for cid in case_ids if draws.get(cid)}
    missing = sorted(unmeasured(draws, case_ids))
    fill = stratified(measured, len(missing)) if measured else [UNSEEN] * len(missing)
    out.update(zip(missing, fill))
    return {cid: out[cid] for cid in case_ids}, sum(len(draws.get(c) or ()) for c in case_ids)


def incumbent_rates(conn, lane: str, key: str, case_ids) -> tuple[dict, int]:
    """case -> the incumbent's stored pass rate, and how many rows it rests on.

    A case with no rows is drawn from its measured per-case rates, else UNSEEN.
    """
    return rates_from(incumbent_profile(conn, lane, key)[0], case_ids)
