"""The loop's closing step: a measured winner becomes the lane's default.

Without this the loop cannot change anything. A candidate can be swept,
inspected, ranked, fetched, screened, measured, beat the incumbent on the
lane's own metric, and the lane goes on serving the constant somebody typed
into a source file. `lh discover --winners` reported that disagreement and
stopped, which makes the gap visible and closes none of it.

WHAT ADOPTION IS NOT. It is not "the challenger scored higher". A run is a
sample, and this project has twice drawn a conclusion from a difference that
was not there: the crowd decay called inert on statistics blind to ordering,
and a temperature trend of 12/27 to 9/27 that is 5 lost against 2 gained,
p=0.45. So a challenger must beat the incumbent on the LANE'S OWN METRIC and
the cell-by-cell comparison must be significant. Anything less is recorded as
a loss, which is the more useful row: it stops the same candidate being
re-proposed every sweep.

THE ADOPTED WINNER IS A STORE FACT, not an edit to a source file. A loop that
rewrites constants would need a commit to take effect and could not be undone
without another one. The lane reads the record and falls back to the typed
constant when nothing has been adopted, so a fresh checkout behaves exactly as
it does today.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field

#: The tier that records an adoption. See memory_store.TIERS.
TIER = "adopt"

#: How an adoption was decided. Either kind serves the machine it was made on;
#: a by-hand one serves every machine only when adopted with --all-machines. #412, #485.
MEASURED, BY_HAND = "measured", "by-hand"
HOW = (MEASURED, BY_HAND)

#: Fewer answers than this and a by-hand adoption needs --force. #485.
MIN_VOTES = 10


class Held(Exception):
    """An adoption that was not written: too few votes, or it cannot fit here. Not a loss."""

#: Below this the difference is not established and the incumbent stays. The
#: exact McNemar test on discordant cells; see harness/paired.py.
ALPHA = 0.05


def alpha_for(tested: int) -> float:
    """The level the next challenger on a holdout faces after `tested` earlier ones: ALPHA over the comparison count. #698."""
    return ALPHA / (max(0, int(tested)) + 1)


def comparisons(conn, lane: str, version: str) -> int:
    """Adopt verdicts already recorded in this lane on this holdout version. #698."""
    head = f"{(lane or '').strip()}: "
    return conn.execute(
        "SELECT COUNT(*) FROM verdicts WHERE tier = ? AND split_version = ? "
        "AND failure_class NOT IN ('inconclusive', 'lane_too_small') AND substr(detail, 1, ?) = ?",
        (TIER, version, len(head), head)).fetchone()[0]


@dataclass(frozen=True)
class Verdict:
    lane: str
    incumbent: str
    challenger: str
    adopt: bool
    why: str
    how: str = MEASURED
    #: reasons.UNDERPOWERED when the gate could not have seen the effect. #479.
    failure_class: str = ""
    #: The split, the power plan and the dev comparison it rests on. #479.
    evidence: dict = field(default_factory=dict)
    votes: int | None = None
    agreement: float | None = None
    forced: bool = False
    all_machines: bool = False
    held: str = ""
    #: The predicate that reopens a verdict waiting on a fact, as memory_store.decide takes it. #993.
    until: str = ""


def better(incumbent: dict, challenger: dict, lane: str = "") -> bool:
    """Is the challenger's summary row better on the lane's own metric?

    Delegates to winners.order_key so there is one ordering rule in the
    project rather than two that can disagree. RULE #254.
    """
    from harness import winners

    names = winners.shared_metrics([incumbent, challenger], lane)
    return winners.order_key(challenger, names, lane) > winners.order_key(incumbent, names, lane)


def decide_by_hand(lane: str, incumbent: str, challenger: str,
                   pairs: list[dict], *, force: bool = False,
                   all_machines: bool = False, min_votes: int = MIN_VOTES,
                   conn=None) -> Verdict:
    """The same closing step for a lane no program can score. Issue #279.

    The two statistical gates are replaced by ONE question a person already
    answered, because for these lanes the gates cannot be computed: there is
    no per-clip style-similarity metric, and a lane's own checkers are blind
    to the thing being compared. `music` scored 4/4 with identical duration
    adherence for both candidates while a person picked different winners in
    different cases -- information the programmatic path structurally could
    not produce.

    UNJUDGED IS NOT A LOSS. `better()` returning False means the challenger
    was measured and came up short; an unjudged lane has not been asked. The
    first is terminal, the second must stay queued, and conflating them
    settles a candidate nobody looked at.
    """
    from harness import human

    won, why = human.lane_verdict(lane, pairs, conn=conn)
    if won is None:
        return Verdict(lane, incumbent, challenger, False, f"not judged: {why}",
                       BY_HAND)
    if not won:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent stays: {why}", BY_HAND)
    if won != challenger:
        return Verdict(lane, incumbent, challenger, False,
                       f"the incumbent was preferred: {why}", BY_HAND)
    votes, agree = human.vote_stats(lane, pairs, conn=conn)
    short = votes < min_votes
    if short and not force:
        return Verdict(lane, incumbent, challenger, False, why, BY_HAND,
                       votes=votes, agreement=agree, held=(
                           f"held: {votes} votes, fewer than {min_votes}; "
                           f"pass --force to adopt on them anyway"))
    return Verdict(lane, incumbent, challenger, True,
                   f"preferred by hand: {why}", BY_HAND, votes=votes, agreement=agree,
                   forced=short, all_machines=all_machines)


def decide(lane: str, incumbent: dict, challenger: dict,
           rows: list[dict] | None = None, split=None, plan=None,
           spec: str = "", tested: int = 0, alpha: float | None = None) -> Verdict:
    """Whether this challenger replaces this incumbent.

    Two gates, both required. The metric gate answers "better on what this lane
    is about". The paired gate answers "by more than the noise". A challenger
    that passes one and not the other is a loss.

    With a `split` both gates read holdout rows only and dev is reported beside
    them; with a `plan` whose power is short a null is underpowered. #479.
    `tested` earlier challengers on this holdout lower the level this one faces. #698.
    `alpha`, when given, is that level less what interim looks spent. #813.
    """
    name_i = incumbent.get("candidate", "")
    name_c = challenger.get("candidate", "")
    alpha = alpha_for(tested) if alpha is None else alpha
    evidence: dict = ({"comparisons": tested + 1, "alpha": alpha}
                      if split is not None or tested else {})
    notes = []
    if abs(alpha - alpha_for(tested)) > 1e-12:
        evidence["alpha"] = alpha
        notes.append(f"tested at alpha {alpha:.4f}: {alpha_for(tested) - alpha:.4f} was spent on interim looks")
    if tested:
        notes.append(f"comparison {tested + 1} on this holdout, so alpha "
                     f"{ALPHA}/{tested + 1} = {alpha_for(tested):.4f}")
    if split is not None:
        from harness import holdout
        evidence["split"] = split.as_dict()
        if rows:
            dev = holdout.rows_on(rows, split, "dev")
            rows = holdout.rows_on(rows, split, "holdout")
            incumbent = _summary(rows, name_i) or incumbent
            challenger = _summary(rows, name_c) or challenger
            if dev:
                d, p, _ = paired_p(dev, name_i, name_c, lane)
                evidence["dev"] = {"gained": d.gained, "lost": d.lost, "p": p}
                notes.append(f"dev: {d.gained} gained, {d.lost} lost, "
                             f"p={p:.2f}")
        if split.too_small:
            notes.append(split.caveat)
    if plan is not None:
        evidence["power"] = plan.as_dict()
        planned = getattr(plan, "alpha", None)
        if planned is not None and abs(planned - alpha_for(tested)) > 1e-12:
            evidence["planned_alpha"] = planned
            notes.append(f"planned at alpha {planned}, tested at {alpha:.4f}: another "
                         f"verdict on this holdout landed during the run")
        if getattr(plan, "dev_skipped", ""):
            evidence["dev"] = {"not_run": plan.dev_skipped}
            notes.append(plan.dev_skipped)
    got = _gates(lane, name_i, name_c, incumbent, challenger, rows, alpha)
    worse = _worse(rows, name_i, name_c, lane, alpha) if rows and not got.adopt else ""
    if worse:
        got = Verdict(lane, name_i, name_c, False, f"{got.why}; {worse}")
    elif not got.adopt and plan is not None and rows:
        got = _lane_too_small(lane, name_i, name_c, got, plan, split) or _null(lane, name_i, name_c, got, plan)
        if got.evidence.get("min_effect"):
            evidence["min_effect"] = got.evidence["min_effect"]
    # A method's calls and latency travel with its verdict, won or lost. #576.
    from harness import methods
    cost = methods.cost_note(incumbent, challenger, spec) if spec else ""
    if cost:
        evidence["cost"] = methods.cost(incumbent, challenger, spec)
    why = "; ".join([got.why, *notes, *([cost] if cost else [])])
    return Verdict(lane, name_i, name_c, got.adopt, why, got.how,
                   got.failure_class, evidence, until=got.until)


def _lane_too_small(lane, name_i, name_c, got: Verdict, plan, split) -> Verdict | None:
    """A null on a lane no repeat could power is a fact about the lane, waiting on its cases, for a model or a method. #993, #1049."""
    from harness import reasons
    limit = lane_limit(lane, plan.as_dict(), name_c)
    if limit is None:
        return None
    more, why = limit
    return Verdict(lane, name_i, name_c, False, f"{why} ({got.why}){_sees(plan)}",
                   failure_class=reasons.LANE_TOO_SMALL,
                   until=cases_until(lane, _have(lane, split, plan.cases), more))


def lane_limit(lane: str, plan: dict, name_c: str = "") -> tuple[int, str] | None:
    """(more lane cases, why) when the plan's holdout is too small or saturated for any repeat, else None. #993, #1049."""
    from harness import power
    cases, need = int(plan.get("cases") or 0), plan.get("cases_needed")
    target = plan.get("target") or power.TARGET
    if plan.get("unmeasured") or float(plan.get("power") or 0.0) >= target:
        return None
    odds = plan.get("odds")
    if need is not None and int(need) > cases:
        more = more_cases(cases, need)
        return more, (f"lane too small, needs {need} holdout cases: {cases} cannot show "
                      f"+{float(plan.get('effect') or 0):.2f} per cell at power {target} at any repeat "
                      f"up to {plan.get('cap')}, so about {more} more {lane} cases are needed before "
                      f"a null says anything about {name_c or 'a challenger'}")
    if odds is not None and float(odds[0]) <= 0:
        return 1, (f"lane too small, needs cases the incumbent fails: it passes all {cases} "
                   f"holdout cases, so no challenger can show a gain on them")
    if plan.get("max_power") is not None and float(plan["max_power"]) <= 0:
        return 1, (f"lane too small: {cases} holdout cases give power 0 even at +1.00 per cell "
                   f"at every repeat up to {plan.get('cap')}")
    return None


def undecidable(lane: str, name_i: str, name_c: str, plan, split=None) -> Verdict | None:
    """The verdict a run whose plan cannot decide at any effect would reach, written instead of running it. #1049."""
    from harness import power, reasons
    if not power.undecidable(plan):
        return None
    more, why = lane_limit(lane, plan.as_dict(), name_c)
    evidence: dict = {"power": plan.as_dict()}
    if split is not None:
        evidence["split"] = split.as_dict()
    return Verdict(lane, name_i, name_c, False,
                   f"{why}; not run: power {plan.max_power:.2f} at +1.00 per cell, so no run "
                   f"of this holdout can decide", failure_class=reasons.LANE_TOO_SMALL,
                   evidence=evidence, until=cases_until(lane, _have(lane, split, plan.cases), more))


def _have(lane: str, split, cases: int) -> int:
    from harness import holdout
    split = split if split is not None else holdout.for_lane(lane)
    return len(set(split.dev) | set(split.holdout)) or cases


def more_cases(cases: int, need) -> int:
    """Lane cases to add before a holdout of `cases` reaches `need`, at least one."""
    import math

    from harness import holdout
    if need is None or int(need) <= int(cases or 0):
        return 1
    return math.ceil((int(need) - int(cases or 0)) / holdout.FRACTION)


def cases_until(lane: str, have: int, more: int = 1) -> str:
    """The predicate a lane-size limit waits on: the lane's `have` cases plus `more`. #993, #1001."""
    return f"cases:{lane}>{int(have) + int(more) - 1}"


def lane_cases(lane: str) -> int:
    """Cases the lane's shipped split has now."""
    from harness import holdout
    now = holdout.for_lane(lane)
    return len(set(now.dev) | set(now.holdout))


def decided_cases(lane: str, split: dict | None = None, plan: dict | None = None) -> int:
    """The lane's cases when a verdict was decided: its split, else its plan, never more than the lane has now. #1053."""
    import math

    from harness import holdout
    split, plan = split or {}, plan or {}
    have = len(set(split.get("dev") or ()) | set(split.get("holdout") or ()))
    held = int(plan.get("cases") or 0)
    if not have and plan.get("side") == "all" and plan.get("cases_run"):
        have = int(plan["cases_run"])
    elif not have and held:
        # Under MIN_HOLDOUT + MIN_DEV cases a lane is too small to split, and its holdout is every case.
        have = held if held < holdout.MIN_HOLDOUT + holdout.MIN_DEV else math.ceil(held / holdout.FRACTION)
    now = lane_cases(lane)
    return min(have, now) if have and now else have or now


def _spent_until(conn, name: str, verdict: Verdict, reason: str) -> str:
    """A limit decline no retest will reopen waits on its lane growing instead. #1001."""
    from harness import reasons
    from harness.memory_store.transitions import retest_spent
    if verdict.adopt or reason != reasons.LIMIT or not name or verdict.until:
        return verdict.until
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()
    if pid is None or not retest_spent(conn, pid[0], TIER, pending=1):
        return ""
    plan = verdict.evidence.get("power") or {}
    return cases_until(verdict.lane, decided_cases(verdict.lane, verdict.evidence.get("split"), plan),
                       more_cases(plan.get("cases") or 0, plan.get("cases_needed")))


def _sees(plan) -> str:
    mde = getattr(plan, "mde", None)
    return (f"; smallest gain this run could see: +{mde:.2f} per cell at power {plan.target}"
            if mde is not None else f"; no gain up to +1.00 is detectable at power {plan.target}")


def _null(lane, name_i, name_c, got: Verdict, plan) -> Verdict:
    """A null is a loss only when the plan could see the smallest gain this lane cares about. #479, #698."""
    from harness import power, reasons
    wanted = power.effect_for(lane)
    seen = getattr(plan, "mde", None)
    seen = plan.effect if seen is None and plan.enough else seen
    tail = f"{'; ' + plan.why if plan.why else ''}"
    sees = _sees(plan)
    if getattr(plan, "unmeasured", False):
        return Verdict(lane, name_i, name_c, False,
                       f"underpowered: the incumbent has no stored draws, so the plan's "
                       f"power {plan.power:.2f} rests on assumed rates and this null is "
                       f"not evidence of no difference ({got.why}){sees}{tail}",
                       failure_class=reasons.UNDERPOWERED)
    if not plan.enough:
        return Verdict(lane, name_i, name_c, False,
                       f"underpowered: power {plan.power:.2f} < {plan.target} to "
                       f"detect +{plan.effect:.2f} per cell at alpha "
                       f"{plan.alpha} over {plan.cells} effective cells, so this null is "
                       f"not evidence of no difference ({got.why}){sees}{tail}",
                       failure_class=reasons.UNDERPOWERED)
    if seen is None or seen > wanted + 1e-9:
        shown = "any gain" if seen is None else f"+{seen:.2f}"
        return Verdict(lane, name_i, name_c, False,
                       f"not shown at {shown}: power {plan.target} reaches only "
                       f"{shown} per cell, above the +{wanted:.2f} this lane adopts for, "
                       f"so a smaller gain is still open ({got.why}){tail}",
                       failure_class=reasons.UNDERPOWERED)
    noise = power.noise_for(lane)
    if seen <= noise + 1e-9:
        return Verdict(lane, name_i, name_c, False,
                       f"{got.why}; no gain of +{seen:.2f} or more per cell at power {plan.target}")
    return Verdict(lane, name_i, name_c, False,
                   f"{got.why}; no gain of +{seen:.2f} or more per cell at power {plan.target}; reruns could see "
                   f"+{noise:.2f}, but a gain under adopt_min_effect +{wanted:.2f} is not worth a switch",
                   evidence={"min_effect": {"noise": noise, "effect": wanted, "seen": round(seen, 4)}})


def _summary(rows: list[dict], name: str) -> dict | None:
    """One candidate's summary row over just these rows."""
    from evals.core import Result, summarize
    mine = [Result(case_id=str(r.get("case_id")), candidate=name,
                   passed=bool(r.get("passed")),
                   seconds=float(r.get("seconds") or 0.0),
                   peak_kb=int(r.get("peak_kb") or 0),
                   detail=str(r.get("detail") or ""),
                   metrics=dict(r.get("metrics") or {}),
                   warnings=list(r.get("warnings") or []),
                   failure_class=str(r.get("failure_class") or ""))
            for r in rows if r.get("candidate") == name]
    if not mine:
        return None
    return {**summarize(mine)[name], "candidate": name}


def lane_cell(rows, name_i: str, name_c: str, lane: str, against: str):
    """The two candidates paired by case on what the lane ranks: its primary metric, or per stratum at the lane's weights. #701, #791."""
    from harness import paired, winners
    if lane in winners.STRATIFIED:
        from evals.core import claims_stratum
        from harness.checks import claims
        return paired.stratified(rows, name_i, name_c, claims_stratum,
                                 {0: claims.RECALL_WEIGHT, 1: 1 - claims.RECALL_WEIGHT}, against)
    return paired.head_to_head(rows, name_i, name_c, winners.PRIMARY.get(lane, ""))


def paired_p(rows, name_i: str, name_c: str, lane: str = "", against: str = "challenger"):
    """The paired cell, its p over independent evidence, and a note when repeats were shrunk.

    Repeats of a case correlate, so gained and lost cells are divided by the
    design effect 1+(r-1)*rho before the sign test: a near-deterministic case
    counts once at any repeat. #591. Rounding goes `against` the side the claim favours. #698.
    """
    from harness import paired, power
    cell = lane_cell(rows, name_i, name_c, lane, against)
    rho, repeat = power.rows_icc([{**r, "passed": power.draw(r, lane)} for r in rows], (name_i, name_c))
    used = power.DEFAULT_RHO if rho is None else rho
    deff = power.design_effect(repeat, used)
    if deff <= 1.0 + 1e-9:
        return cell, cell.p, ""
    if against == "incumbent":
        gained, lost = paired.shrink(cell.gained, cell.lost, deff)
    else:
        lost, gained = paired.shrink(cell.lost, cell.gained, deff)
    p = paired.sign_test(min(gained, lost), gained + lost)
    return cell, p, (f"{gained} gained against {lost} lost once correlated "
                     f"repeats are counted as cases (rho {used:.2f}"
                     f"{'' if rho is not None else ' assumed'}, repeat "
                     f"{repeat:.1f})")


def _worse(rows, name_i: str, name_c: str, lane: str = "", alpha: float = ALPHA) -> str:
    """Why the challenger is significantly worse, else "". Power to see a gain does not bear on it. #594."""
    cell, p, shrunk = paired_p(rows, name_i, name_c, lane, against="incumbent")
    if cell.lost <= cell.gained or p > alpha:
        return ""
    return (f"significantly worse: {cell.lost} lost against {cell.gained} "
            f"gained, p={p:.2f}{f' ({shrunk})' if shrunk else ''}")


def _gates(lane, name_i, name_c, incumbent, challenger, rows, alpha: float = ALPHA) -> Verdict:
    if not better(incumbent, challenger, lane):
        return Verdict(lane, name_i, name_c, False,
                       "does not beat the incumbent on the lane's metric")
    if not rows:
        return Verdict(lane, name_i, name_c, False,
                       "no paired rows, so the difference is unmeasured")
    cell, p, shrunk = paired_p(rows, name_i, name_c, lane)
    shrunk = f" ({shrunk})" if shrunk else ""
    if not cell.discordant and not cell.unchanged:
        return Verdict(lane, name_i, name_c, False,
                       f"{name_i} and {name_c} share no case in this run, so "
                       f"there is nothing to compare")
    if cell.gained <= cell.lost:
        # A two-sided test calls a difference either way significant; only a gain adopts. #1302.
        return Verdict(lane, name_i, name_c, False,
                       f"better on the metric, but the paired cells do not favour it: {cell.lost} lost "
                       f"against {cell.gained} gained{shrunk}")
    if p > alpha:
        return Verdict(lane, name_i, name_c, False,
                       f"better on the metric, but {cell.lost} lost against "
                       f"{cell.gained} gained is p={p:.2f}{shrunk}, so the "
                       f"difference is not established")
    return Verdict(lane, name_i, name_c, True,
                   f"beats {name_i} on the lane's metric, {cell.gained} gained "
                   f"against {cell.lost} lost, p={p:.2f}{shrunk}")


def confirmation_cells(rows, split, screened=frozenset(), fresh: bool = False) -> list[dict]:
    """Rows on the cases the gate was not decided on, less those the challenger's screen ran; a fresh run of a too-small lane uses every case. #725."""
    from harness import holdout
    if split is None or not rows:
        return []
    if split.too_small:
        got = list(rows) if fresh else []
    else:
        got = holdout.rows_on(rows, split, "dev")
    return [r for r in got if holdout.base_id(r.get("case_id")) not in screened]


def screened_cases(conn, lane: str, keys) -> frozenset:
    """The cases a screen run of any of these receipt keys ran in this lane. #725."""
    from harness import holdout
    keys = [k for k in keys if k]
    if not keys:
        return frozenset()
    marks = ",".join("?" * len(keys))
    got = conn.execute("SELECT DISTINCT x.case_id FROM results x JOIN runs u ON u.id = x.run_id "
                       f"WHERE u.lane = ? AND u.tier = 'screen' AND x.candidate IN ({marks})",
                       ((lane or "").strip().lower(), *keys)).fetchall()
    return frozenset(holdout.base_id(r[0]) for r in got)


def _confirm_sees(cells, name_i: str, lane: str) -> str:
    from harness import power
    draws, _ = power.draws_from(cells, name_i, lane)
    rates = [sum(v) / len(v) for v in draws.values() if v]
    rho, repeat = power.rows_icc([{**r, "passed": power.draw(r, lane)} for r in cells], (name_i,))
    got = power.mde(rates, max(1, round(repeat)), ALPHA, power.DEFAULT_RHO if rho is None else rho, power.TARGET)
    return (f"; smallest gain these cells could see: +{got:.2f} per cell at power {power.TARGET}"
            if got is not None else f"; no gain up to +1.00 is detectable on them at power {power.TARGET}")


def confirm(verdict: Verdict, rows, split, screened=frozenset(), *, fresh: bool = False) -> Verdict:
    """A holdout win serves only once the cells it was not decided on also show it better at ALPHA; with none it waits for a night run. #725."""
    from dataclasses import replace

    from harness import holdout, reasons
    if not verdict.adopt or verdict.how != MEASURED:
        return verdict
    cells = confirmation_cells(rows, split, screened, fresh)
    base = {**(verdict.evidence.get("confirm") or {}), "screened": sorted(screened)}
    if not cells:
        return replace(verdict, adopt=False, failure_class=reasons.CONFIRMING,
                       why=(f"held for confirmation: no case outside the holdout ran, so the incumbent serves "
                            f"until a night run of the dev cases confirms it ({verdict.why})"),
                       evidence={**verdict.evidence, "confirm": base})
    lane, name_i, name_c = verdict.lane, verdict.incumbent, verdict.challenger
    cases = len({holdout.base_id(r["case_id"]) for r in cells})
    cell, p, shrunk = paired_p(cells, name_i, name_c, lane)
    evidence = {**verdict.evidence, "confirm": {**base, "cases": cases, "gained": cell.gained,
                                                "lost": cell.lost, "p": p}}
    head = (f"{cases} dev case(s): {cell.gained} gained against {cell.lost} lost, p={p:.3f}"
            f"{f' ({shrunk})' if shrunk else ''}")
    inc, ch = _summary(cells, name_i), _summary(cells, name_c)
    if inc and ch and better(inc, ch, lane) and cell.gained > cell.lost and p <= ALPHA:
        return replace(verdict, why=f"{verdict.why}; confirmed on {head}", evidence=evidence)
    worse = _worse(cells, name_i, name_c, lane)
    if worse:
        return replace(verdict, adopt=False, failure_class="", evidence=evidence,
                       why=f"won the holdout, but on {cases} dev case(s) it is {worse} ({verdict.why})")
    return replace(verdict, adopt=False, failure_class=reasons.UNDERPOWERED, evidence=evidence,
                   why=(f"won the holdout, not confirmed on {head}{_confirm_sees(cells, name_i, lane)}; "
                        f"this null is not evidence of no difference ({verdict.why})"))


def confirm_argv(vid: int) -> list[str]:
    import sys
    return [sys.executable, "-m", "harness.cli", "adopt", "--confirm", str(int(vid))]


def queue_confirmation(conn, vid: int, verdict: Verdict, now: float | None = None,
                       start: float | None = None) -> dict | None:
    """Queue tonight's dev run (or one at `start`) that confirms or refuses a held holdout win, once per verdict. #725."""
    import os
    import time

    from harness import paths, workqueue
    argv = confirm_argv(vid)
    # The job this runs in is not the continuation it queues. #1357.
    mine = os.environ.get(workqueue.JOB_ENV, "").strip()
    mine = int(mine) if mine.isdigit() else None
    have = conn.execute("SELECT id FROM jobs WHERE argv = ? AND state IN (?, ?) AND id IS NOT ?",
                        (json.dumps(argv), workqueue.PENDING, workqueue.RUNNING, mine)).fetchone()
    if have is not None:
        return None
    return workqueue.add(argv, title=(f"confirm {verdict.lane}: {verdict.challenger} over {verdict.incumbent} "
                                      f"on dev (verdict {vid})"),
                         cwd=str(paths.REPO), requested_by="adopt",
                         not_before=(workqueue.night_start(time.time() if now is None else now)
                                     if start is None else start),
                         night=True, conn=conn)


#: Candidates that exist to measure local models against. #374.
REFERENCE_PREFIXES = ("claude-code:", "cloud-")


def is_reference(candidate: str) -> bool:
    return (candidate or "").startswith(REFERENCE_PREFIXES)


def outcome_of(verdict: Verdict) -> tuple[str, str]:
    """The (outcome, reason) record() writes for this verdict."""
    from harness import reasons
    outcome, reason = reasons.CLASSES.get(verdict.failure_class, (
        "declined", reasons.LIMIT
        if verdict.failure_class in (reasons.UNDERPOWERED, reasons.INCONCLUSIVE, reasons.LANE_TOO_SMALL,
                                     reasons.CONFIRMING)
        else reasons.CANDIDATE))
    return ("measured" if verdict.adopt else outcome), reason


def record(conn, verdict: Verdict, spec: str = "",
           run_id: int | None = None) -> int:
    """Write an adoption, or the loss, on the candidate that ran. #407, #412.

    `spec` is what ran; `verdict.challenger` is used when it is one. The
    verdict lands on the candidate's proposal, or on the candidate alone for
    a typed default or a command-line spec, and never creates a proposal. An
    adoption is also an `adoptions` row, which is what every reader asks.
    """
    from harness import candidates
    from harness import memory_store as ms

    if verdict.held:
        raise Held(verdict.held)
    if is_reference(verdict.challenger) or is_reference(spec):
        verdict = Verdict(verdict.lane, verdict.incumbent, verdict.challenger,
                          False, f"reference model; never a lane default "
                          f"({verdict.why})", verdict.how)
    spec = spec or verdict.challenger
    verdict = _control_guard(verdict, spec)
    verdict = _schema_guard(verdict, spec)
    outcome, reason = outcome_of(verdict)
    serve = verdict.adopt
    detail = f"{verdict.lane}: {verdict.why}"
    # A text-lane spec is the proposal's own name; anything else maps by row.
    cid = candidates.ensure(conn, spec, proposal=spec, lane=verdict.lane)
    if cid is None:
        raise ValueError(f"{spec!r} is not a spec any runner takes, so an "
                         f"adoption of it could never be served")
    row = candidates.get(conn, spec)
    if verdict.adopt and verdict.how == BY_HAND:
        ok, why = fit(conn, cid, ms.remember_machine(conn))
        if not ok:
            raise Held(f"refused on this machine: {spec} {why}")
    vid = ms.decide(conn, row["proposal"] or "", outcome, tier=TIER,
                    detail=detail[:200], candidate_id=cid, run_id=run_id,
                    reason=reason, until=_spent_until(conn, row["proposal"] or "", verdict, reason))
    if verdict.failure_class or verdict.evidence:
        conn.execute(
            "UPDATE verdicts SET failure_class = ?, split_version = ?, "
            "power = ? WHERE id = ?",
            (verdict.failure_class,
             (verdict.evidence.get("split") or {}).get("version", ""),
             json.dumps({**(verdict.evidence.get("power") or {}),
                         "dev": verdict.evidence.get("dev"),
                         **({"partial": verdict.evidence["partial"]}
                            if verdict.evidence.get("partial") else {}),
                         **({"cost": verdict.evidence["cost"]}
                            if verdict.evidence.get("cost") else {}),
                         **({"comparisons": verdict.evidence["comparisons"],
                             "alpha": verdict.evidence.get("alpha", ALPHA)}
                            if verdict.evidence.get("comparisons") else {}),
                         **({"planned_alpha": verdict.evidence["planned_alpha"]}
                            if "planned_alpha" in verdict.evidence else {}),
                         **({"confirm": verdict.evidence["confirm"]}
                            if verdict.evidence.get("confirm") else {}),
                         **({"min_effect": verdict.evidence["min_effect"]}
                            if verdict.evidence.get("min_effect") else {})}), vid))
        conn.commit()
    floor = verdict.evidence.get("min_effect")
    if floor:
        from harness import cuts
        cuts.cut("adopt_min_effect", f"{verdict.lane}: {spec} declined on a null that could see "
                 f"+{floor['seen']:.2f}, above the lane's +{floor['noise']:.2f} noise", kept=0, dropped=1, conn=conn)
    if serve:
        if verdict.how not in HOW:
            raise ValueError(f"unknown adoption kind {verdict.how!r}")
        mid = conn.execute("SELECT machine_id FROM verdicts WHERE id = ?",
                           (vid,)).fetchone()
        mid = mid["machine_id"] if mid else None
        inc = _incumbent_id(conn, verdict.lane, verdict.incumbent)
        conn.execute(
            "INSERT OR IGNORE INTO adoptions (lane, candidate_id, incumbent_id, "
            "run_id, verdict_id, machine_id, how, adopted_at, all_machines, "
            "votes, agreement, forced, cost) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (verdict.lane.strip().lower(), cid, inc, run_id, vid, mid,
             verdict.how, _now(), int(verdict.all_machines), verdict.votes,
             verdict.agreement, int(verdict.forced),
             json.dumps(cost(conn, cid, inc, mid), sort_keys=True)))
        conn.commit()
        from harness import gateway
        if verdict.lane.strip().lower() in gateway.TEXT_LANES:
            try:
                gateway.refresh_gateway()
            except OSError:
                pass
    return vid


def _control_guard(verdict: Verdict, spec: str) -> Verdict:
    """A negative control is never a lane default; one that wins says the gate or the cases are suspect. #993."""
    from harness import methods
    if not verdict.adopt or not methods.is_control(spec):
        return verdict
    return Verdict(verdict.lane, verdict.incumbent, verdict.challenger, False,
                   f"negative control won, so this lane's method verdicts are suspect until it is "
                   f"explained; a control is never a lane default ({verdict.why})", verdict.how,
                   verdict.failure_class, verdict.evidence)


def _schema_guard(verdict: Verdict, spec: str) -> Verdict:
    """A schema lane's win on an engine that cannot enforce its schema is the harness's gap, not a loss. #572."""
    from harness import gateway, reasons, serving
    lane = verdict.lane.strip().lower()
    if not verdict.adopt or lane not in gateway.SCHEMA_LANES or serving.enforces_schema(spec):
        return verdict
    return Verdict(verdict.lane, verdict.incumbent, verdict.challenger, False,
                   f"not adopted: {spec} is not served by llama-server, so the {lane} "
                   f"lane's response_format would be refused or silently dropped "
                   f"({verdict.why})", verdict.how, reasons.REFUSED_BY_GATEWAY,
                   verdict.evidence)


def _now() -> float:
    import time
    return time.time()


def _incumbent_id(conn, lane: str, name: str) -> int | None:
    """The candidates row of what the lane served before, if it can be named."""
    from harness import candidates
    if not name:
        return None
    got = candidates.get(conn, name)
    if got:
        return got["id"]
    try:
        from harness import screen
        return candidates.ensure(
            conn, screen.candidate_for(lane, name) or name,
            lane=lane)
    except Exception:  # noqa: BLE001
        return None


#: Read the adoptions this machine serves; see here().
HERE = object()


def here(conn) -> tuple[int, ...]:
    """This machine's id, as runs.here() finds it by fingerprint. #356, #415."""
    from harness import runs
    try:
        return tuple(runs.here(conn))
    except Exception:  # noqa: BLE001
        return ()


def _ids(conn, machine) -> tuple:
    if machine is HERE:
        return here(conn)
    if isinstance(machine, (tuple, list, set)):
        return tuple(machine)
    return () if machine is None else (machine,)


def _resolve(conn, machine) -> tuple[dict[str, dict], dict[str, dict]]:
    """(lane -> served row, lane -> newer by-hand row refused for not fitting)."""
    ids = _ids(conn, machine)
    marks = ",".join("?" * len(ids)) or "NULL"
    rows = conn.execute(
        "SELECT a.*, c.spec FROM adoptions a "
        "JOIN candidates c ON c.id = a.candidate_id "
        "WHERE a.all_machines = 1 OR a.machine_id IS NULL "
        f"OR a.machine_id IN ({marks}) "
        "ORDER BY a.adopted_at, a.id", ids).fetchall()
    out: dict[str, dict] = {}
    refused: dict[str, dict] = {}
    for row in rows:
        if is_reference(row["spec"]):
            continue
        if row["how"] == BY_HAND:
            ok, why = fit(conn, row["candidate_id"], ids[0] if ids else None)
            if not ok:
                refused[row["lane"]] = {**dict(row), "why": why}
                continue
        out[row["lane"]] = dict(row)
        refused.pop(row["lane"], None)
    return out, refused


def current(conn, machine=HERE) -> dict[str, dict]:
    """lane -> the adoption row a machine serves, with its spec.

    The newest adoption for the lane made on that machine, or made with
    --all-machines and fitting there. One no machine is recorded for serves
    everywhere, as every adoption did before #412. `machine` is HERE, a machine
    id, or a tuple of ids. A reference model is never a lane default. #374, #412, #485.
    """
    return _resolve(conn, machine)[0]


def refused(conn, machine=HERE) -> list[dict]:
    """By-hand adoptions this machine would serve but cannot fit, newest per lane. #485."""
    return sorted(_resolve(conn, machine)[1].values(), key=lambda r: r["lane"])


def _ceiling_gb(conn, machine_id) -> float:
    if machine_id is not None:
        row = conn.execute("SELECT ceiling_gb FROM machines WHERE id = ?",
                           (machine_id,)).fetchone()
        if row:
            return float(row["ceiling_gb"] or 0)
    from harness import memory_store as ms
    return float(ms.this_machine().get("ceiling_gb") or 0)


_GIB_KB = 1024 ** 2


def fit(conn, candidate_id: int, machine_id) -> tuple[bool, str]:
    """Whether a candidate fits a machine's memory ceiling, and the evidence. #485.

    A passing stored run on the machine is proof it ran there, whatever its peak.
    Else the largest measured peak anywhere, else the stored size; neither is
    served but said.
    """
    ran = conn.execute(
        "SELECT COUNT(*) AS n, MAX(x.peak_kb) AS p FROM results x "
        "JOIN runs r ON r.id = x.run_id WHERE x.candidate_id = ? "
        "AND r.machine_id = ? AND x.passed = 1",
        (candidate_id, machine_id)).fetchone()
    if ran["n"]:
        return True, (f"ran here: {ran['n']} passing row(s), peak "
                      f"{(ran['p'] or 0) / _GIB_KB:.1f} GiB")
    peak = conn.execute(
        "SELECT x.peak_kb AS p, r.machine_id AS m FROM results x "
        "JOIN runs r ON r.id = x.run_id WHERE x.candidate_id = ? "
        "AND x.peak_kb > 0 ORDER BY x.peak_kb DESC LIMIT 1",
        (candidate_id,)).fetchone()
    size = conn.execute(
        "SELECT p.size_bytes AS b FROM candidates c JOIN proposals p "
        "ON p.id = c.proposal_id WHERE c.id = ?", (candidate_id,)).fetchone()
    if peak:
        need = peak["p"] / _GIB_KB
        source = f"measured peak {need:.1f} GiB (machine {peak['m']})"
    elif size and size["b"]:
        need = size["b"] / 1024 ** 3
        source = f"stored size {need:.1f} GiB"
    else:
        return True, "size unknown: no stored size or measured peak, so not checked"
    ceiling = _ceiling_gb(conn, machine_id)
    if not ceiling:
        return True, f"{source}; no memory ceiling recorded for this machine"
    ok = need <= ceiling
    return ok, (f"{source} {'fits' if ok else 'is over'} the "
                f"{ceiling:.1f} GiB ceiling")


def _measured(conn, candidate_id, machine_id) -> dict:
    """Median seconds and peak GiB over a candidate's passing rows on one machine, and the row counts."""
    if candidate_id is None:
        return {"median_s": None, "peak_gb": None, "rows": 0, "passed": 0}
    rows = conn.execute(
        "SELECT x.seconds AS s, x.peak_kb AS p, x.passed AS ok FROM results x "
        "JOIN runs r ON r.id = x.run_id WHERE x.candidate_id = ? "
        "AND r.machine_id = ?", (candidate_id, machine_id)).fetchall()
    ok = [r for r in rows if r["ok"]]
    peak = max((r["p"] or 0 for r in ok), default=0) / _GIB_KB
    return {"median_s": round(statistics.median(r["s"] for r in ok), 3) if ok else None,
            "peak_gb": round(peak, 3) if peak else None,
            "rows": len(rows), "passed": len(ok)}


def cost(conn, candidate_id, incumbent_id, machine_id) -> dict:
    """The new model's median latency and peak against the previous one's, on one machine."""
    new = _measured(conn, candidate_id, machine_id)
    old = _measured(conn, incumbent_id, machine_id)
    return {"machine_id": machine_id, **new,
            **{f"incumbent_{k}": v for k, v in old.items()}}


def cost_text(cost: dict) -> str:
    """One line for a cost dict, saying what is missing rather than guessing it."""
    med, imed = cost.get("median_s"), cost.get("incumbent_median_s")
    if med is None:
        return "cost: no stored run of the new model on this machine"
    out = f"cost: median {med:.1f}s"
    out += (f" against {imed:.1f}s ({med / imed:.1f}x)" if imed
            else " (no stored run of the previous model here)")
    peak, ipeak = cost.get("peak_gb"), cost.get("incumbent_peak_gb")
    if peak:
        out += f", peak {peak:.1f} GiB" + (f" against {ipeak:.1f} GiB"
                                           if ipeak else "")
    if cost.get("rows"):
        out += f"; {cost.get('passed', 0)} of {cost['rows']} rows passed here"
    return out


def describe(row: dict, machine_id=None) -> str:
    """How an adoption was made and where it serves, for report and judge. #485."""
    if row.get("all_machines"):
        scope = "all machines"
    elif row.get("machine_id") is None:
        scope = "every machine (recorded before scoping)"
    elif row["machine_id"] == machine_id:
        scope = "this machine only"
    else:
        scope = f"machine {row['machine_id']} only"
    out = f"{row.get('how') or MEASURED}, {scope}"
    if row.get("votes") is not None:
        out += f", {row['votes']} votes"
        if row.get("agreement") is not None:
            out += f", agreement {row['agreement']:.2f}"
    if row.get("forced"):
        out += ", forced"
    return out


def everywhere(conn) -> dict[str, set[str]]:
    """lane -> every spec some machine in the store serves by adoption."""
    out: dict[str, set[str]] = {}
    mids = [r["machine_id"] for r in conn.execute(
        "SELECT DISTINCT machine_id FROM adoptions").fetchall()]
    for mid in mids:
        for lane, row in current(conn, mid).items():
            out.setdefault(lane, set()).add(row["spec"])
    return out


def adopted(conn, machine=HERE) -> dict[str, str]:
    """The lane -> spec this machine serves by adoption."""
    return {lane: row["spec"] for lane, row in current(conn, machine).items()}


def lane_defaults(conn=None, machine=HERE, typed=None) -> dict[str, str]:
    """What every lane serves now: its adoption here, else the typed default.

    Never raises: a missing, locked or older store leaves the typed defaults.
    """
    if typed is None:
        from harness import winners
        typed = winners.typed()
    close = conn is None
    try:
        if conn is None:
            from harness import memory_store as ms
            conn = ms.connect()
        got = adopted(conn, machine)
    except Exception:  # noqa: BLE001
        got = {}
    finally:
        if close and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return {**dict(typed), **got}


def default_for(lane: str, fallback: str, conn=None, machine=HERE) -> str:
    """What this lane serves right now: the adopted winner, else the constant.

    RESOLVED AT CALL TIME. `DEFAULT_TTS_MODEL` reaches its callers as a default
    ARGUMENT, captured when the function is defined, so rebinding the constant
    changes nothing -- the same trap that made SpeechRunner's declared voice
    unreachable (#195). An adoption that cannot take effect without a restart
    is a report with extra steps.

    Never raises and never blocks a generation. A store that is missing,
    locked or older than this code leaves the lane on its typed constant, which
    is what a fresh checkout does anyway.
    """
    if not lane:
        return fallback
    key = lane.strip().lower()
    return lane_defaults(conn, machine, typed={key: fallback}).get(key) \
        or fallback
