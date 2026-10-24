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
from fractions import Fraction
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
#: Minutes one challenger's paired run may spend per sweep before it pauses. #591, #813.
BUDGET_MIN = 120.0
#: The repeat run when the powered one does not fit the budget.
FALLBACK_REPEAT = 3
#: A stochastic lane whose correlation is unmeasured runs at least this, so the run measures it.
MEASURING_REPEAT = 2
#: Decode rate for a reply-budget estimate by hw_model (non-word characters as _), tokens per second; any other machine gets completion.MIN_DECODE_TOK_S. #628, #673, #696.
DECODE_TOK_S = {"Mac17_15": 145.0}
#: A paired run may run this far past max(budget, projection) before it is stopped. #673.
DEADLINE_GRACE = 1.25
#: Hours a discover loop may run from its start; a measurement running at it pauses for the next sweep. #806, #813.
SWEEP_CEILING_H = 6.0
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
@functools.lru_cache(maxsize=None)
def _critical(d: int, alpha: float) -> int:
    """Fewest gains of d discordant cells that the two-sided test rejects on."""
    total = 2 ** d
    level = Fraction(alpha).limit_denominator(10 ** 9)
    tail = 0
    term = 1
    for k in range(0, d // 2 + 1):
        if k:
            term = term * (d - k + 1) // k
        tail += term
        if 2 * tail * level.denominator > level.numerator * total:
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


def mde(rates, repeat: int, alpha: float, rho: float, target: float) -> float | None:
    """Smallest per-cell gain in (0, 1] this many cases and repeats detect at `target`, rounded up to 0.001."""
    rates = list(rates)
    if not rates or power(rates, 1.0, repeat, alpha, rho) < target:
        return None
    lo, hi = 0.0, 1.0
    for _ in range(30):
        mid = (lo + hi) / 2
        if power(rates, mid, repeat, alpha, rho) >= target:
            hi = mid
        else:
            lo = mid
    e = math.ceil(hi * 1000 - 1e-9) / 1000
    while e < 1.0 and power(rates, e, repeat, alpha, rho) < target:
        e = round(e + 0.001, 3)
    return e


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
    #: Which split side runs, model calls per case across both candidates, and how many cases. #673.
    side: str = "all"
    calls: int = 2
    cases_run: int | None = None
    dev_skipped: str = ""
    deadline_s: float | None = None
    #: The smallest gain this plan detects at `target`; None when no gain reaches it. #698.
    mde: float | None = None
    #: The incumbent had no stored draws, so every rate is UNSEEN and the power is a guess. #698.
    unmeasured: bool = False
    #: Where each candidate's seconds per call came from, and the inputs. #696.
    estimate: dict | None = None
    #: Per-cell P(gained), P(lost) at `effect` over the holdout, for interim looks. #813.
    odds: tuple | None = None
    #: Budgets (sweeps) the projection spans; a run past one pauses and resumes. #813.
    sweeps: int | None = None
    #: Power at +1.00 per cell at the most repeat any run spends; 0 means no run of this holdout can decide. #1049.
    max_power: float | None = None
    #: Incumbent cells taken from stored draws under its content identity (harness.reuse.plan). #1094.
    reuse: dict | None = None

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def enough(self) -> bool:
        return self.power >= self.target


def plan(rates, effect: float | None = None, *, stochastic: bool = True,
         alpha: float | None = None, target: float = TARGET, cap: int = CAP,
         repeat: int | None = None, observed: int = 0,
         rho: float | None = None, unmeasured: bool | None = None) -> Plan:
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
    most = max(cap, repeat or 0) if stochastic else 1
    extra = {"rho": rho, "rho_measured": measured, "cases_needed": need,
             "unmeasured": observed <= 0 if unmeasured is None else unmeasured,
             "max_power": power(rates, 1.0, most, alpha, rho if measured else 0.0) if rates else None}

    def at(r: int) -> float:
        return power(rates, effect, r, alpha, rho)

    def made(r, got, capped, why):
        return Plan(r, got, effective_cells(k, r, rho), k, effect, alpha, target,
                    cap, capped, stochastic, observed, why, **extra,
                    mde=mde(rates, r, alpha, rho, target))

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
    if r < cap:
        from harness import cuts
        cuts.cut("power_plateau", "repeats past the power plateau", kept=r, dropped=cap - r)
    if not measured and r < min(MEASURING_REPEAT, cap):
        from harness import cuts
        cuts.cut("power_measuring_repeat", "repeat raised so the run measures its correlation", kept=r)
        r = max(r, min(MEASURING_REPEAT, cap))
    if r < cap and rho > 0:
        why = (f"repeats of a case are correlated (rho {rho:.2f}"
               f"{'' if measured else ', assumed until measured'}), so no repeat "
               f"up to {cap} reaches {target}: power {best:.2f} at most, already "
               f"at repeat {r}; {more}")
        return made(r, powers[r - 1], False, why)
    return made(cap, powers[-1], True,
                f"capped at repeat {cap} with power {powers[-1]:.2f}; {more}")


def undecidable(plan: Plan) -> bool:
    """No run of this holdout can decide: power 0 even at +1.00 per cell and every repeat up to cap. #1049."""
    return not plan.unmeasured and plan.max_power is not None and plan.max_power <= 0.0


def too_small(plan: Plan) -> int | None:
    """Holdout cases needed before any repeat can see the plan's effect, when the holdout has fewer; else None. #993."""
    if plan.enough or plan.unmeasured or plan.cases_needed is None:
        return None
    return plan.cases_needed if plan.cases_needed > plan.cases else None


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
                      calls: int = 2) -> float | None:
    """Wall time of a paired run: every case run, every repeat, every model call of both candidates. #673."""
    if median_s is None:
        return None
    return cases * repeat * calls * median_s


def machine_key(hw_model: str | None = None) -> str:
    """This machine's (or `hw_model`'s) key in DECODE_TOK_S: hw_model with non-word characters as _. #696."""
    import re

    from harness import memory_store as ms
    hw = ms.this_machine().get("hw_model", "") if hw_model is None else hw_model
    return re.sub(r"\W", "_", hw or "")


def decode_tok_s(hw_model: str | None = None) -> float:
    """This machine's (or `hw_model`'s) registered decode rate, else the slowest the harness allows for. #696."""
    from harness import completion
    if not isinstance(DECODE_TOK_S, dict):
        return float(DECODE_TOK_S)
    return DECODE_TOK_S.get(machine_key(hw_model), completion.MIN_DECODE_TOK_S)


def estimated_seconds(lane: str, tok_s: float | None = None) -> float | None:
    """Seconds per call if every reply spends the lane's whole reply budget; None for a lane with no text. #673."""
    from harness import completion
    budget = completion.budget((lane or "").strip().lower())
    return budget / (tok_s or decode_tok_s()) if budget else None


def floor_seconds(lane: str) -> float | None:
    """Seconds per call if every reply spends the lane's budget at completion.MIN_DECODE_TOK_S. #696."""
    from harness import completion
    return estimated_seconds(lane, completion.MIN_DECODE_TOK_S)


def deadline(chosen: "Plan") -> float | None:
    """When a slice that did not pause itself is stopped: DEADLINE_GRACE past its budget, plus one case to finish. #673, #813."""
    if chosen.budget_s is None:
        return None
    cells = (chosen.cases_run or 0) * chosen.repeat
    one = (chosen.projected_s or 0.0) / cells if cells else 0.0
    return chosen.budget_s * DEADLINE_GRACE + one


def _hm(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{max(m, 1)}m"


def within_budget(chosen: Plan, rates, *, cases_run: int, median_s: float | None,
                  budget_s: float, explicit: bool = False, calls: int = 2) -> Plan:
    """The planned repeat if its projected time fits `budget_s`, else the fallback and what power would cost. #591."""
    def cost(r):
        return projected_seconds(cases_run, r, median_s, calls)

    run = {"calls": calls, "cases_run": cases_run}
    if explicit or not chosen.stochastic:
        return replace(chosen, projected_s=cost(chosen.repeat), budget_s=budget_s,
                       needed_repeat=chosen.repeat, **run)
    if median_s is None:
        r = min(chosen.repeat, FALLBACK_REPEAT)
        if r < chosen.repeat:
            from harness import cuts
            cuts.cut("power_fallback_repeat", "repeat of an unpriced lane", kept=r, dropped=chosen.repeat - r)
        note = (f"no measured seconds per case in this lane, so the cost of "
                f"repeat {chosen.repeat} is unknown; ran repeat {r}")
    elif cost(chosen.repeat) <= budget_s:
        return replace(chosen, projected_s=cost(chosen.repeat), budget_s=budget_s,
                       needed_repeat=chosen.repeat, **run)
    else:
        r = max(1, min(FALLBACK_REPEAT, chosen.repeat, int(budget_s // cost(1))))
        note = (f"repeat {chosen.repeat} for power {chosen.power:.2f} would take "
                f"{_hm(cost(chosen.repeat))}, over the {_hm(budget_s)} budget; "
                f"ran repeat {r}")
    got = plan(rates, chosen.effect, stochastic=True, alpha=chosen.alpha,
               target=chosen.target, cap=chosen.cap, repeat=r,
               observed=chosen.observed,
               rho=chosen.rho if chosen.rho_measured else None,
               unmeasured=chosen.unmeasured)
    return replace(got, needed_repeat=chosen.repeat, projected_s=cost(r),
                   budget_s=budget_s, **run,
                   why="; ".join(x for x in (note, got.why) if x))


def _row_metric(row, name: str):
    try:
        got = row["metrics"]
    except (KeyError, IndexError):
        return None
    if isinstance(got, str):
        import json
        try:
            got = json.loads(got or "{}")
        except ValueError:
            return None
    value = (got or {}).get(name)
    return float(value) if isinstance(value, (int, float)) else None


def draw(row, lane: str = "") -> int:
    """A row's planning draw: where the gate pairs on a lane metric, whether the row's is at its best, else its pass bit. #1007."""
    from harness import winners
    name = winners.PRIMARY.get((lane or "").strip().lower(), "")
    value = _row_metric(row, name) if name else None
    if value is None:
        return int(bool(row["passed"]))
    from evals.core import direction_of
    return int(value >= 1.0 if direction_of(name) == "higher" else value <= 0.0)


def draws_from(rows, key: str, lane: str = "") -> tuple[dict[str, list[int]], float | None]:
    """case -> one candidate's draws (see draw), and its mean seconds per case: wall time is a sum. #796, #1007."""
    from harness import holdout
    by: dict[str, list[int]] = {}
    secs = []
    for r in rows:
        if r["candidate"] != key:
            continue
        by.setdefault(holdout.base_id(r["case_id"]), []).append(draw(r, lane))
        if r["seconds"] is not None:
            secs.append(float(r["seconds"]))
    return by, (statistics.fmean(secs) if secs else None)


def reply_settings(receipt, lane: str) -> tuple[int, tuple]:
    """(max_tokens, budget_ladder) a stored receipt ran at; a receipt from before #628 ran at the legacy budget. #673."""
    import json
    from evals.core import legacy_budget
    try:
        got = json.loads(receipt or "{}")
    except ValueError:
        got = {}
    budget = got.get("max_tokens")
    budget = legacy_budget(got.get("modality") or lane) if budget is None else int(budget)
    return budget, tuple(int(n) for n in got.get("budget_ladder") or ())


def _candidate_rows(conn, lane: str, key: str, tiers=("measure",)) -> list:
    lane = (lane or "").strip().lower()
    marks = ",".join("?" * len(tiers))
    return conn.execute(
        "SELECT x.case_id, x.passed, x.seconds, x.candidate, x.metrics, u.receipt, u.machine_id FROM results x "
        f"JOIN runs u ON u.id = x.run_id WHERE u.lane = ? AND u.tier IN ({marks}) AND x.candidate = ?",
        (lane, *tiers, key)).fetchall()


def _median(rows, lane: str, key: str, settings: tuple | None, machines) -> float | None:
    if machines is not None:
        rows = [r for r in rows if r["machine_id"] in set(machines)]
    if settings is not None:
        rows = [r for r in rows if reply_settings(r["receipt"], lane) == tuple(settings)]
    return draws_from(rows, key)[1]


def mean_seconds(conn, lane: str, key: str, settings: tuple, machines) -> float | None:
    """One receipt key's mean seconds per case in a lane, at `settings` on `machines`. #810."""
    return _median(_candidate_rows(conn, lane, key), (lane or "").strip().lower(), key, settings, machines)


def served_keys(conn, lane: str, spec: str = "", cid: int | None = None) -> list[str]:
    """The receipt keys a served model's measure rows carry, under its own name and its renames, read only. #740."""
    from harness import candidates, models
    lane = (lane or "").strip().lower()
    if not spec and cid is not None:
        row = conn.execute("SELECT spec FROM candidates WHERE id = ?", (cid,)).fetchone()
        spec = row["spec"] if row else ""

    def key(name):
        try:
            return candidates.key_of(name) or name
        except Exception:  # noqa: BLE001
            return name

    names = {spec, models.resolve(spec), *models.old_names(spec), *models.old_names(models.resolve(spec))} if spec else set()
    names = sorted(n for n in names | {key(n) for n in names if n} if n)
    marks = ",".join("?" * len(names))
    ids = {r["id"] for r in conn.execute(
        f"SELECT id FROM candidates WHERE spec IN ({marks}) OR receipt_key IN ({marks})",
        (*names, *names))} if names else set()
    if cid is not None:
        ids.add(cid)
    ids_marks = ",".join("?" * len(ids))
    keys = [r["candidate"] for r in conn.execute(
        "SELECT DISTINCT x.candidate FROM results x JOIN runs u ON u.id = x.run_id "
        f"WHERE u.lane = ? AND u.tier = 'measure' AND (x.candidate_id IN ({ids_marks}) OR x.candidate IN ({marks})) "
        "ORDER BY x.candidate", (lane, *ids, *names))] if names or ids else []
    return keys if keys or not spec else [key(spec)]


def _served_rows(conn, lane: str, spec: str = "", cid: int | None = None, on_metric: bool = True):
    lane = (lane or "").strip().lower()
    draws: dict[str, list[int]] = {}
    rows = []
    for key in served_keys(conn, lane, spec, cid):
        got = _candidate_rows(conn, lane, key)
        for case, oks in draws_from(got, key, lane if on_metric else "")[0].items():
            draws.setdefault(case, []).extend(oks)
        rows += [dict(r, candidate="") for r in got]
    return draws, rows


def served_profile(conn, lane: str, spec: str = "", settings: tuple | None = None, machines=None,
                   cid: int | None = None, on_metric: bool = True) -> tuple[dict[str, list[int]], float | None]:
    """The served incumbent's draws per case over every key its rows carry, store-wide; its mean seconds only at `settings` on `machines`. #673, #696, #740."""
    draws, rows = _served_rows(conn, lane, spec, cid, on_metric)
    return draws, _median(rows, (lane or "").strip().lower(), "", settings, machines)


def served_bound(conn, lane: str, spec: str, settings: tuple, machines) -> tuple[float | None, str]:
    """Seconds per case bounded by the served incumbent's receipts at other reply budgets here, and the basis. #796.

    A reply at budget B takes no longer than one at a larger budget, nor than B/b times one cut at b;
    the least such bound, capped at the whole-budget estimate."""
    lane = (lane or "").strip().lower()
    want = int(settings[0])
    rows = [r for r in _served_rows(conn, lane, spec)[1]
            if machines is None or r["machine_id"] in set(machines)]
    by: dict[int, list] = {}
    for r in rows:
        b = reply_settings(r["receipt"], lane)[0]
        if b > 0 and r["seconds"] is not None:
            by.setdefault(b, []).append(r)
    best, basis = None, ""
    for b, got in sorted(by.items()):
        mean = draws_from(got, "")[1]
        scale = 1.0 if b >= want else want / b
        if mean is not None and (best is None or mean * scale < best):
            best = mean * scale
            basis = (f"bounded at {best:.0f}s from the incumbent's {b}-token receipt(s) here "
                     f"({mean:.0f}s{'' if scale == 1.0 else f' x {want}/{b}'})")
    cap = estimated_seconds(lane)
    if best is not None and cap is not None and best > cap:
        best, basis = cap, f"{basis}, capped at the whole {want}-token budget ({cap:.0f}s)"
    return best, basis


def unseen_note(draws: dict) -> str:
    """What a plan from no stored incumbent draws assumes, or "" when it has some. #740."""
    if any(draws.values()):
        return ""
    return f"the incumbent's pass rate is unmeasured (no stored measure rows), so the plan assumes {UNSEEN:g}"


def stored_size(conn, key: str) -> int:
    """Bytes of the proposal a receipt key or spec runs as, 0 when none is stored. #696."""
    row = conn.execute(
        "SELECT MAX(p.size_bytes) AS b FROM candidates c JOIN proposals p ON p.id = c.proposal_id "
        "WHERE c.receipt_key = ? OR c.spec = ?", (key, key)).fetchone()
    return int(row["b"] or 0) if row else 0


def decode_rate(conn, lane: str, keys, settings: tuple | None, machines, tiers=("measure",)) -> float | None:
    """Mean reply tokens per second the receipt keys' rows record in a lane, at `settings` on `machines`. #864."""
    import json
    keys = [k for k in dict.fromkeys(keys) if k]
    if not keys:
        return None
    lane = (lane or "").strip().lower()
    rows = conn.execute(
        "SELECT x.metrics, u.receipt, u.machine_id FROM results x JOIN runs u ON u.id = x.run_id "
        f"WHERE u.lane = ? AND u.tier IN ({','.join('?' * len(tiers))}) "
        f"AND x.candidate IN ({','.join('?' * len(keys))})", (lane, *tiers, *keys)).fetchall()
    rates = []
    for r in rows:
        if machines is not None and r["machine_id"] not in set(machines):
            continue
        if settings is not None and reply_settings(r["receipt"], lane) != tuple(settings):
            continue
        rate = json.loads(r["metrics"] or "{}").get("tokens_per_s")
        if isinstance(rate, (int, float)) and rate > 0:
            rates.append(float(rate))
    return statistics.fmean(rates) if rates else None


def challenger_seconds(conn, lane: str, key: str, *, incumbent: str, incumbent_s: float | None,
                       settings: tuple | None, machines, incumbent_keys=()) -> tuple[float | None, str]:
    """Seconds per call of a challenger here: its own screen or measure median, else scaled by size, else the floor. #696."""
    lane = (lane or "").strip().lower()
    # A screen's few cases price its decode speed, not the holdout's heavy-tailed reply lengths; speed is any budget's. #864.
    mine = decode_rate(conn, lane, (key,), None, machines, ("screen", "measure"))
    theirs = decode_rate(conn, lane, (incumbent, *incumbent_keys), None, machines)
    if incumbent_s is not None and mine and theirs:
        return incumbent_s * theirs / mine, "decode ratio"
    own = _median(_candidate_rows(conn, lane, key, ("screen", "measure")), lane, key, settings, machines)
    if own is not None:
        return own, "measured"
    mine, theirs = stored_size(conn, key), max(stored_size(conn, k) for k in (incumbent, *incumbent_keys))
    if incumbent_s is not None and mine and theirs:
        return incumbent_s * mine / theirs, "size ratio"
    floor = floor_seconds(lane)
    if floor is not None:
        return floor, "floor"
    return incumbent_s, "incumbent"


def _base_key(spec: str) -> str:
    """The receipt key of a method's base, or of the spec itself."""
    from harness import candidates, methods
    base = methods.base_of(spec) or spec
    try:
        return candidates.key_of(base) or base
    except Exception:  # noqa: BLE001
        return base


def expected_calls(conn, lane: str, spec: str, settings: tuple | None, *also) -> float:
    """Calls one attempt of `spec` is expected to take, from its base's stored per-case pass rates. #807."""
    from harness import methods
    if not methods.base_of(spec):
        return methods.calls(spec)
    for key in (_base_key(spec), *also):
        rows = _candidate_rows(conn, lane, key, ("screen", "measure"))
        if settings is not None:
            rows = [r for r in rows if reply_settings(r["receipt"], lane) == tuple(settings)]
        draws = draws_from(rows, key)[0]
        if draws:
            return methods.expected_calls(spec, [statistics.fmean(d) for d in draws.values()])
    return methods.calls(spec)


def pair_cost(conn, lane: str, *, incumbent: str, incumbent_spec: str, incumbent_s: float | None,
              challenger: str = "", settings: tuple | None, machines,
              incumbent_basis: str = "") -> tuple[float | None, float, dict]:
    """Mean seconds per call over both candidates, their expected calls per case, and how each was priced. #696, #796, #807."""
    tok_s = decode_tok_s()
    inc_source = "bounded" if incumbent_basis else "measured"
    if incumbent_s is None:
        incumbent_s = estimated_seconds(lane, tok_s)
        inc_source = "estimated" if incumbent_s is not None else "unknown"
    inc_calls = expected_calls(conn, lane, incumbent_spec, settings) if incumbent_spec else 1
    if incumbent_s is not None and inc_source in ("measured", "bounded"):
        incumbent_s = incumbent_s / inc_calls  # a method row's seconds are every call of the case

    if challenger:
        key = _base_key(challenger)
        known = served_keys(conn, lane, incumbent_spec) if incumbent_spec else []
        same = key in (incumbent, _base_key(incumbent_spec or incumbent), *known)
        if same:
            ch_s, ch_source = incumbent_s, inc_source
        else:
            ch_s, ch_source = challenger_seconds(conn, lane, key, incumbent=incumbent, incumbent_s=incumbent_s,
                                                 settings=settings, machines=machines, incumbent_keys=known)
        ch_calls = expected_calls(conn, lane, challenger, settings, *((incumbent, *known) if same else ()))
    else:
        ch_s, ch_source, ch_calls = incumbent_s, "like incumbent", inc_calls
    calls = round(inc_calls + ch_calls, 2)
    mean = None if incumbent_s is None or ch_s is None else (inc_calls * incumbent_s + ch_calls * ch_s) / calls
    est = {"machines": list(machines or ()), "settings": list(settings or ()), "decode_tok_s": tok_s,
           "incumbent_s": incumbent_s, "incumbent_source": inc_source, "incumbent_calls": inc_calls,
           "incumbent_basis": incumbent_basis,
           "challenger_s": ch_s, "challenger_source": ch_source, "challenger_calls": ch_calls}
    return mean, calls, est


def receipt_here(env: dict | None) -> bool:
    """Whether a receipt file's environment names this machine; one from before hosts matches its board. #696."""
    from harness import machine
    from harness import memory_store as ms
    env = env or {}
    mine = ms.this_machine().get("fingerprint") or ""
    theirs = machine.fingerprint(*(str(env.get(k) or "") for k in ("hw_model", "os", "arch", "host")))
    if theirs == "unknown":
        return False
    return theirs == mine or (not env.get("host") and mine.rsplit("/", 1)[0] == theirs)


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
