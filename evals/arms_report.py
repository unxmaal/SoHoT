"""Arms of one model that differ by context, each paired with a baseline arm by task, per split side. #995.

    soh repo-report RUN [RUN...] --arms [--baseline SPEC] [--effect D]
    soh repo-report [RUN] --plan [--effect D]
"""
from __future__ import annotations

import random

from evals import repo_report as R
from evals.importers import history
from harness import holdout, paired, power, reasons

#: Held-out first: it is the side a result is quoted from.
ORDER = tuple(reversed(holdout.SIDES))
#: Repeats the plan prints power for.
PLAN_REPEATS = (1, 2, 3, 4, 6)
#: Within-task correlations the plan prices tasks at, beside the measured or assumed one.
RHOS = (1.0, 0.5, 0.0)
COST = ("tokens_in", "tokens_out", "turns", "wall_s")
_IN = ("prompt_tokens", "cache_read_tokens", "cache_creation_tokens")


def _cost(row: dict) -> dict:
    """A draw's own usage record; a quantity the row never recorded is None, not zero."""
    m = row.get("metrics") or {}
    got = [m[k] for k in _IN if m.get(k) is not None]
    return {"tokens_in": sum(map(int, got)) if got else None,
            "tokens_out": None if m.get("completion_tokens") is None else int(m["completion_tokens"]),
            "turns": None if m.get("turns") is None else int(m["turns"]),
            "wall_s": None if row.get("seconds") is None else float(row["seconds"])}


def _keys(runs, rows) -> dict:
    """(run id, candidate) -> arm key: the candidate, or `run N candidate` when two runs hold it."""
    seen: dict = {}
    for r in rows:
        seen.setdefault(r["candidate"], set()).add(r["run_id"])
    return {(rid, c): (c if len(ids) == 1 else f"run {rid} {c}") for c, ids in seen.items() for rid in ids}


def context_of(runs, run_id: int, candidate: str) -> dict:
    """The context receipt an arm ran with; none for a candidate with no context recorded."""
    for r in runs:
        if r["id"] == run_id:
            got = (r["receipt"].get("contexts") or {}).get(candidate)
            if got:
                return dict(got)
    return {"spec": "none", "kind": "none", "digest": ""}


def _pick(order: list, contexts: dict, baseline: str | None) -> str:
    if baseline:
        hits = [k for k in order if k == baseline or contexts[k]["spec"] == baseline]
        if len(hits) != 1:
            raise R.Refused(f"--baseline {baseline} matches {len(hits)} arms of {', '.join(order)}")
        return hits[0]
    nones = [k for k in order if contexts[k]["spec"] == "none"]
    return nones[0] if nones else order[0]


def _suite(rows, order, task, runs) -> tuple[dict, dict]:
    """case -> arm -> [(passed, failure_class, cost)], valid cases only, and what was set aside."""
    draws: dict = {}
    for r in sorted(rows, key=lambda r: r.get("repeat_index") or 1):
        draws.setdefault(holdout.base_id(r["case_id"]), {}).setdefault(r["arm"], []).append(
            (bool(r["passed"]), r.get("failure_class") or "", _cost(r)))
    no_key = sorted(k for k in draws if k not in task)
    unpaired = sorted(k for k in draws if k in task and set(draws[k]) != set(order))
    variants: dict = {}
    for k in draws:
        if k in task and k not in unpaired:
            variants.setdefault(task[k][0], set()).add(task[k][1])
    single = sorted(k for k in draws if k in task and k not in unpaired
                    and variants[task[k][0]] != set(history.VARIANTS))
    invalid = sorted({k for r in runs for k, v in ((r["receipt"] or {}).get("validation") or {}).items()
                      if v != "valid" and k in draws})
    never = sorted(k for k, d in draws.items() if any(fc in reasons.NEVER_RAN for x in d.values() for _, fc, _ in x))
    out = set(no_key) | set(unpaired) | set(single) | set(invalid) | set(never)
    return ({k: d for k, d in draws.items() if k not in out},
            {"no_task_key": no_key, "unpaired": unpaired, "single_variant": single, "not_valid": invalid,
             "never_ran": never})


def _units(suite: dict, task: dict, order) -> dict:
    """task -> arm -> variant -> [passes, draws] plus the arm's cost sums over the task."""
    out: dict = {}
    for k, by in suite.items():
        t, v = task[k]
        for arm in order:
            u = out.setdefault(t, {}).setdefault(arm, {"spec": [0, 0], "symptom": [0, 0], "n": 0,
                                                      **{c: [0.0, 0] for c in COST}})
            for p, _, cost in by[arm]:
                u[v][0] += p
                u[v][1] += 1
                u["n"] += 1
                for c in COST:
                    if cost[c] is not None:
                        u[c][0] += cost[c]
                        u[c][1] += 1
    return out


def _rate(units, arm, variants=history.VARIANTS) -> float | None:
    k = sum(u[arm][v][0] for u in units for v in variants)
    n = sum(u[arm][v][1] for u in units for v in variants)
    return k / n if n else None


def _mean(units, arm, metric) -> float | None:
    """Mean per draw over the draws that recorded the metric."""
    n = sum(u[arm][metric][1] for u in units)
    return sum(u[arm][metric][0] for u in units) / n if n else None


def _boot(units: list, stat, *, resamples: int, seed: int, confidence: float = 0.95) -> dict | None:
    """The statistic over the tasks, and a percentile interval resampling whole tasks."""
    point = stat(units)
    if point is None or not units:
        return None
    rng, got = random.Random(seed), []
    for _ in range(resamples):
        x = stat([units[rng.randrange(len(units))] for _ in units])
        if x is not None:
            got.append(x)
    got.sort()
    tail = (1 - confidence) / 2
    lo, hi = got[int(tail * len(got))], got[min(int((1 - tail) * len(got)), len(got) - 1)]
    return {"difference": round(point, 4), "low": round(lo, 4), "high": round(hi, 4)}


def _diff(f, base, arm):
    def stat(us):
        a, b = f(us, arm), f(us, base)
        return None if a is None or b is None else a - b
    return stat


def _sign(diffs: list[float], alpha: float) -> dict:
    up, down = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    p = paired.sign_test(min(up, down), up + down)
    return {"higher": up, "lower": down, "tied": len(diffs) - up - down, "p": round(p, 4),
            "testable": paired.sign_test(0, up + down) <= alpha}


def _task_rate(u, arm, variants=history.VARIANTS) -> float:
    n = sum(u[arm][v][1] for v in variants)
    return sum(u[arm][v][0] for v in variants) / n if n else 0.0


def _power(units: list, base: str, arm: str, suite: dict, task: dict, effect: float, alpha: float) -> dict:
    """Power of the paired task test at this many tasks and repeats, from the baseline's per-task rates."""
    rates = [_task_rate(u, base) for u in units]
    rows = [{"candidate": a, "case_id": f"{k}#{i}", "passed": p} for k, d in suite.items() for a in (base, arm)
            for i, (p, _, _) in enumerate(d[a], 1)]
    rho, repeat = power.rows_icc(rows, [base, arm])
    use = power.DEFAULT_RHO if rho is None else rho
    r = max(1, round(repeat))
    got = power.power(rates, effect, r, alpha, use) if rates else 0.0
    need = power.cases_needed(rates, effect, rho=use, stochastic=rho is not None, alpha=alpha) if rates else None
    return {"effect": effect, "power": round(got, 3), "enough": got >= power.TARGET, "repeat": r,
            "rho": None if rho is None else round(rho, 4), "rho_used": use,
            "mde": power.mde(rates, r, alpha, use, power.TARGET) if rates else None, "tasks_needed": need}


def _word(sign: dict, pw: dict, alpha: float) -> str:
    """differs, or why a null is not "no effect": never a bare "no difference" when underpowered."""
    if sign["p"] <= alpha:
        return "differs: " + ("higher" if sign["higher"] > sign["lower"] else "lower")
    if not pw["enough"]:
        need = f"; {pw['tasks_needed']} tasks would reach {power.TARGET}" if pw["tasks_needed"] else ""
        return f"underpowered (power {pw['power']:.2f} for +{pw['effect']}{need}), not evidence of no effect"
    return f"no difference of +{pw['mde']} or more detected"


def _side(units: dict, order, base, suite, task, *, effect, alpha, resamples, seed) -> dict:
    us = [units[t] for t in sorted(units)]
    out = {"tasks": len(us), "cases": len(suite), "arms": {}}
    for arm in order:
        a = {"rate": {v: _rate(us, arm, vs) for v, vs in (("all", history.VARIANTS), ("spec", ("spec",)),
                                                           ("symptom", ("symptom",)))},
             "draws": sum(u[arm]["n"] for u in us),
             "resolved": sum(u[arm][v][0] for u in us for v in history.VARIANTS),
             "cost": {c: _mean(us, arm, c) for c in COST}}
        a["interval"] = _boot(us, lambda x, arm=arm: _rate(x, arm), resamples=resamples, seed=seed)
        if arm != base:
            a["vs"] = {v: _boot(us, _diff(lambda x, w, vs=vs: _rate(x, w, vs), base, arm), resamples=resamples, seed=seed)
                       for v, vs in (("all", history.VARIANTS), ("spec", ("spec",)), ("symptom", ("symptom",)))}
            a["cost_vs"] = {c: _boot(us, _diff(lambda x, w, c=c: _mean(x, w, c), base, arm), resamples=resamples,
                                     seed=seed) for c in COST}
            a["sign"] = _sign([_task_rate(u, arm) - _task_rate(u, base) for u in us], alpha)
            a["power"] = _power(us, base, arm, suite, task, effect, alpha)
            a["verdict"] = _word(a["sign"], a["power"], alpha)

            def gap(x, arm=arm):
                s, p = _rate(x, arm, ("symptom",)), _rate(x, arm, ("spec",))
                bs, bp = _rate(x, base, ("symptom",)), _rate(x, base, ("spec",))
                return None if None in (s, p, bs, bp) else (s - bs) - (p - bp)
            a["symptom_gain_minus_spec_gain"] = {
                **(_boot(us, gap, resamples=resamples, seed=seed) or {}),
                **_sign([(_task_rate(u, arm, ("symptom",)) - _task_rate(u, base, ("symptom",)))
                         - (_task_rate(u, arm, ("spec",)) - _task_rate(u, base, ("spec",))) for u in us], alpha)}
        out["arms"][arm] = a
    return out


def report(runs, rows, cases, *, baseline: str | None = None, effect: float = power.DEFAULT_EFFECT,
           resamples: int = 2000, seed: int = 1) -> dict:
    """Every arm against the baseline arm, per split side, the task as the unit and repeats its replicates."""
    alpha = R._alpha()
    keys = _keys(runs, rows)
    rows = [{**r, "arm": keys[(r["run_id"], r["candidate"])]} for r in rows]
    order = list(dict.fromkeys(r["arm"] for r in rows))
    if len(order) < 2:
        raise R.Refused(f"an arms report needs two arms or more; these runs hold {len(order)}")
    contexts = {keys[k]: context_of(runs, *k) for k in keys}
    base = _pick(order, contexts, baseline)
    order = [base] + [k for k in order if k != base]
    task = R.tasks_of(cases)
    suite, aside = _suite(rows, order, task, runs)
    sides = {}
    for side in ORDER:
        mine = {k: d for k, d in suite.items() if side == "all" or history.side_of(task[k][0]) == side}
        sides[side] = _side(_units(mine, task, order), order, base, mine, task, effect=effect, alpha=alpha,
                            resamples=resamples, seed=seed)
    return {"baseline": base, "arms": order, "contexts": contexts, "alpha": alpha, "effect": effect,
            "runs": [r["id"] for r in runs], "set_aside": aside, "sides": sides,
            "labels": R.labels({k: task[k] for k in suite}),
            "split": {"seed": history.SPLIT_SEED, "fraction": history.HOLDOUT_FRACTION}}


def _f(x, fmt="{:.3f}") -> str:
    return "?" if x is None else fmt.format(x)


def _iv(d, signed=True) -> str:
    if not d:
        return "?"
    f = "{:+.3f}" if signed else "{:.3f}"
    return f"{f.format(d['difference'])} [{f.format(d['low'])}, {f.format(d['high'])}]"


def _name(rep, arm) -> str:
    ctx = rep["contexts"].get(arm) or {}
    tag = ctx.get("spec") or "none"
    return f"{arm} ({tag}{'@' + ctx['digest'] if ctx.get('digest') else ''})"


def text(rep: dict) -> str:
    out = [f"arms against {_name(rep, rep['baseline'])}, alpha {rep['alpha']}, effect +{rep['effect']} per-task "
           f"lift; split seed {rep['split']['seed']}, held-out fraction {rep['split']['fraction']}"]
    for arm in rep["arms"]:
        out.append(f"  arm {_name(rep, arm)}")
    for why, ids in rep["set_aside"].items():
        if ids:
            out.append(f"set aside ({why.replace('_', ' ')}): {', '.join(ids)}")
    for side in ORDER:
        s = rep["sides"][side]
        out.append(f"\n{side}: {s['cases']} cases from {s['tasks']} tasks"
                   + (" (held out; quote these)" if side == "holdout" else
                      " (the only side a skill may be tuned on)" if side == "dev" else ""))
        out.append(f"  {'arm':40s} {'all':>7s} {'95% task CI':>17s} {'spec':>6s} {'symptom':>7s} "
                   f"{'draws':>6s} {'in tok':>9s} {'out tok':>8s} {'turns':>6s} {'wall s':>7s}")
        for arm in rep["arms"]:
            a = s["arms"][arm]
            ci = a["interval"]
            band = f"[{ci['low']:.2f}, {ci['high']:.2f}]" if ci else "?"
            out.append(f"  {arm[:40]:40s} {_f(a['rate']['all']):>7s} {band:>17s} "
                       f"{_f(a['rate']['spec'], '{:.2f}'):>6s} {_f(a['rate']['symptom'], '{:.2f}'):>7s} {a['draws']:>6d} "
                       f"{_f(a['cost']['tokens_in'], '{:.0f}'):>9s} {_f(a['cost']['tokens_out'], '{:.0f}'):>8s} "
                       f"{_f(a['cost']['turns'], '{:.1f}'):>6s} {_f(a['cost']['wall_s'], '{:.1f}'):>7s}")
        for arm in rep["arms"][1:]:
            a = s["arms"][arm]
            sg, pw, g = a["sign"], a["power"], a["symptom_gain_minus_spec_gain"]
            out.append(f"  {arm} minus baseline: {_iv(a['vs']['all'])} (spec {_iv(a['vs']['spec'])}, symptom "
                       f"{_iv(a['vs']['symptom'])}); tasks higher {sg['higher']}, lower {sg['lower']}, tied "
                       f"{sg['tied']}; sign p = {sg['p']}: {a['verdict']}")
            rho = pw["rho"] if pw["rho"] is not None else f"unmeasured, {pw['rho_used']} used"
            out.append(f"    power {pw['power']:.2f} at {s['tasks']} tasks x repeat {pw['repeat']} for +{pw['effect']}"
                       f" (rho {rho}); "
                       f"MDE {pw['mde']}; tasks needed {pw['tasks_needed']}")
            out.append(f"    cost per draw: tokens in {_iv(a['cost_vs']['tokens_in'])}, out {_iv(a['cost_vs']['tokens_out'])}, "
                       f"turns {_iv(a['cost_vs']['turns'])}, wall s {_iv(a['cost_vs']['wall_s'])}")
            out.append(f"    symptom gain minus spec gain: {_iv(g if 'difference' in g else None)}; tasks "
                       f"{g['higher']} up, {g['lower']} down, sign p = {g['p']}")
    return "\n".join(out)


def plan(cases, runs=(), rows=(), *, baseline: str | None = None, effect: float = power.DEFAULT_EFFECT,
         repeats=PLAN_REPEATS) -> dict:
    """Tasks x repeats needed per side to see `effect`, from a stored baseline's per-task rates or UNSEEN."""
    alpha = R._alpha()
    task = R.tasks_of(cases)
    variants: dict = {}
    for t, v in task.values():
        variants.setdefault(t, set()).add(v)
    # A task missing a variant is set aside by the report, so the plan does not count it.
    task = {k: tv for k, tv in task.items() if variants[tv[0]] == set(history.VARIANTS)}
    by_task: dict = {t: [] for t, _ in task.values()}
    rho = None
    measured_from = ""
    if rows:
        keys = _keys(runs, rows)
        rows = [{**r, "arm": keys[(r["run_id"], r["candidate"])]} for r in rows]
        order = list(dict.fromkeys(r["arm"] for r in rows))
        contexts = {keys[k]: context_of(runs, *k) for k in keys}
        base = _pick(order, contexts, baseline)
        mine = [r for r in rows if r["arm"] == base and holdout.base_id(r["case_id"]) in task
                and (r.get("failure_class") or "") not in reasons.NEVER_RAN]
        for r in mine:
            by_task[task[holdout.base_id(r["case_id"])][0]].append(int(bool(r["passed"])))
        rho, _ = power.rows_icc([{**r, "candidate": base} for r in mine], [base])
        measured_from = base
    out = {"effect": effect, "alpha": alpha, "target": power.TARGET, "baseline": measured_from,
           "rho": rho, "sides": {}}
    seen = [sum(v) / len(v) for v in by_task.values() if v]
    for side in ORDER:
        keys = sorted(t for t in by_task if side == "all" or history.side_of(t) == side)
        draws = {t: by_task[t] for t in keys}
        rates, _ = power.rates_from(draws, keys) if keys else ({}, 0)
        rates = list(rates.values())
        chosen = power.plan(rates, effect, alpha=alpha, rho=rho, observed=sum(map(len, draws.values())))
        out["sides"][side] = {
            "tasks": len(keys), "measured_tasks": sum(1 for t in keys if draws[t]),
            "power": {str(r): round(power.power(rates, effect, r, alpha, power.DEFAULT_RHO if rho is None else rho), 3)
                      for r in repeats} if rates else {},
            "repeat": chosen.repeat, "plan_power": round(chosen.power, 3), "enough": chosen.enough,
            "mde": chosen.mde, "tasks_needed": chosen.cases_needed, "too_small": power.too_small(chosen),
            "why": _why(chosen, len(keys)),
            "needed_by_rho": {str(x): power.cases_needed(rates, effect, rho=x, alpha=alpha, cap=max(repeats))
                              for x in RHOS} if rates else {}}
    out["unseen"] = not seen
    return out


def _why(chosen, tasks: int) -> str:
    """The plan's reason in tasks, not power.plan's holdout-case wording."""
    if chosen.enough:
        return ""
    if chosen.cases_needed is None:
        return f"no number of tasks up to {power.MAX_CASES} reaches {power.TARGET}"
    more = max(0, chosen.cases_needed - tasks)
    lead = (f"repeats of a task are correlated (rho {chosen.rho:.2f}"
            f"{'' if chosen.rho_measured else ', assumed until measured'}), so repeat {chosen.repeat} is the most "
            f"worth running" if chosen.rho > 0 else f"repeat {chosen.repeat} gives power {chosen.power:.2f}")
    return f"{lead}; {chosen.cases_needed} tasks would reach {power.TARGET}, {more} more than this side has"


def plan_text(p: dict) -> str:
    rho = (f"rho {p['rho']:.2f} measured" if p["rho"] is not None
           else f"rho unmeasured, {power.DEFAULT_RHO} assumed (repeats then add nothing until a repeat measures it)")
    src = (f"per-task rates of {p['baseline']}" if p["baseline"] and not p["unseen"]
           else f"no stored baseline rows, every task assumed at {power.UNSEEN}")
    out = [f"plan: detect +{p['effect']} per-task lift at alpha {p['alpha']}, power {p['target']}; {src}; {rho}"]
    for side in ORDER:
        s = p["sides"][side]
        pw = ", ".join(f"r{r} {v:.2f}" for r, v in s["power"].items())
        small = (f"; too small: {s['too_small']} tasks needed" if s["too_small"] else "")
        out.append(f"  {side:8s} {s['tasks']} tasks ({s['measured_tasks']} measured): power {pw}; plan repeat "
                   f"{s['repeat']} at {s['plan_power']:.2f}; MDE {s['mde']}; tasks needed {s['tasks_needed']}{small}")
        if s["why"]:
            out.append(f"           {s['why']}")
        if s["needed_by_rho"]:
            out.append(f"           tasks needed at repeat up to {max(map(int, s['power']))}: " + ", ".join(
                f"rho {r} {n}" for r, n in s["needed_by_rho"].items()))
    return "\n".join(out)
