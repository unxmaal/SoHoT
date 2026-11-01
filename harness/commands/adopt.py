"""`soh adopt`: make a measured run a lane's winner, or say what power each lane's gate needs."""
from __future__ import annotations

import contextlib
import json
import math
from pathlib import Path

from harness import lanes, paths
from harness.commands.common import emit, err, lent_store, note
from harness.commands import measure as measure_cmd


def _run_name(run: Path) -> str:
    """A run under the runs dir by its directory name, anything else by path."""
    try:
        return run.resolve().relative_to((paths.home() / "runs").resolve()).as_posix()
    except ValueError:
        return str(run)


def cmd_adopt(a) -> int:
    """The discovery loop's paired measure-and-adopt, for a named challenger."""
    if getattr(a, "confirm", None) is not None:
        return measure_cmd.confirm_job(a.confirm)
    if getattr(a, "power", False):
        return cmd_power(a)
    if getattr(a, "from_measurement", False):
        return _dry_run(a) if getattr(a, "dry_run", False) else _from_measurement(a)
    if not a.lane or not a.challenger:
        return err("adopt needs --lane and --challenger, or --power")
    lane = lanes.canonical(a.lane)
    if lane not in lanes.ALL:
        return err(f"unknown lane {a.lane!r}; known: {', '.join(lanes.ALL)}")
    return measure_cmd._measure_and_adopt(a, {"name": a.challenger, "lane": lane})


def argv_screen_refusal(argv) -> str:
    """Why a queued `soh adopt --lane repo --challenger X` waits for X's repo screen, or "". #1353."""
    import argparse
    argv = [str(x) for x in argv]
    if "adopt" not in argv:
        return ""
    ap = argparse.ArgumentParser(add_help=False)
    for flag in ("--lane", "--challenger", "--confirm"):
        ap.add_argument(flag, default="")
    for flag in ("--unscreened", "--power", "--from-measurement"):
        ap.add_argument(flag, action="store_true")
    got, _ = ap.parse_known_args(argv[argv.index("adopt") + 1:])
    if got.confirm or got.power or got.from_measurement or not got.challenger:
        return ""
    return measure_cmd._screen_refusal(got, lanes.canonical(got.lane or ""), got.challenger)


def _dry_run(a) -> int:
    """`--from-measurement --dry-run` on one connection, lent to every reader. #1426."""
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        with ms.lend(conn):
            return _from_measurement(a)
    finally:
        conn.close()


def _from_measurement(a) -> int:
    """`soh adopt --lane L --from-measurement`: a never-passing typed incumbent gives way to the best measured local candidate. #1110."""
    from harness import adopt, screen, winners
    from harness.commands import measure as m
    lane = lanes.canonical(a.lane or "")
    typed = winners.typed().get(lane, "")
    if not typed:
        return err(f"--from-measurement needs --lane with a typed default; known: {', '.join(sorted(winners.typed()))}")
    served = adopt.default_for(lane, typed)
    inc_spec = screen.candidate_for(lane, served) or served
    zero = m._zero_pass(lane, inc_spec)
    if not zero:
        note(f"{lane}: {served} is adopted or has passed a stored case (or has fewer stored cases than the "
             f"zero_pass_min_cases knob), so its incumbent is not taken from measurement")
        emit(lane=lane, incumbent=served, taken=None)
        return 0
    got = m.take_measured(lane, inc_spec, zero, dry_run=getattr(a, "dry_run", False))
    emit(lane=lane, incumbent=served, zero_pass=zero, taken=got.challenger if got else None)
    return 0


def _receipts(files) -> dict[str, list[dict]]:
    """lane -> each receipt file given, as its receipt, environment and rows."""
    out: dict[str, list[dict]] = {}
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        lane = lanes.canonical((data.get("receipt") or {}).get("modality") or "")
        out.setdefault(lane, []).append({"receipt": data.get("receipt") or {},
                                         "environment": data.get("environment") or {},
                                         "rows": list(data.get("rows") or [])})
    return out


def _row(r: dict) -> dict:
    return {"candidate": r.get("candidate"), "case_id": r.get("case_id"),
            "passed": r.get("passed"), "seconds": r.get("seconds"), "metrics": r.get("metrics")}


def _profile(lane: str, receipts: dict, conn) -> tuple[str, str, dict, float | None, tuple, list]:
    """(incumbent key, its spec, its draws per case, its median seconds here at the lane's budget, settings, machines)."""
    from harness import adopt, candidates, power, reply_cap, runs, screen, winners
    served = adopt.default_for(lane, winners.typed().get(lane, ""))
    spec = (screen.candidate_for(lane, served) or served) if served else ""
    try:
        key = candidates.key_of(spec) if spec else ""
    except Exception:  # noqa: BLE001
        key = ""
    settings = (reply_cap.cap_for(conn, lane, [spec or served])[0], ())
    machines = runs.here(conn)
    if lane in receipts:
        sets = [[_row(r) for r in got["rows"]] for got in receipts[lane]]
        key = power.control_of(sets, prefer=[k for k in (key, spec, served) if k])
        draws, _ = power.draws_from([r for rows in sets for r in rows], key, lane)
        timed = [_row(r) for got in receipts[lane] if power.receipt_here(got["environment"])
                 and power.reply_settings(json.dumps(got["receipt"]), lane) == settings for r in got["rows"]]
        return key, spec or served, draws, power.draws_from(timed, key)[1], settings, machines
    key = key or spec
    draws, median = (power.served_profile(conn, lane, spec, settings, machines)
                     if spec else ({}, None))
    return key, spec or served, draws, median, settings, machines


def _hm(seconds) -> str:
    if seconds is None:
        return "time unknown"
    m = int(round(seconds / 60))
    return f"~{m // 60}h{m % 60:02d}m" if m >= 60 else f"~{max(m, 1)}m"


def cmd_power(a) -> int:
    """Per lane: the repeat and holdout size power 0.8 needs, and what that run would cost. #591."""
    from evals.run import STOCHASTIC_MODALITIES
    from harness import adopt, holdout, power

    receipts = _receipts(getattr(a, "receipt", None) or [])
    challenger = getattr(a, "challenger", "") or ""
    budget = float(getattr(a, "power_budget_min", None) or power.BUDGET_MIN) * 60
    rows = []
    held = contextlib.ExitStack()
    conn = held.enter_context(lent_store())
    try:
        every = holdout.splits()
        want = lanes.canonical(a.lane) if a.lane else ""
        if want and want not in every:
            return err(f"no cases for lane {a.lane!r}; lanes with cases: "
                       f"{', '.join(sorted(every))}")
        for lane in [want] if want else sorted(every):
            split = every[lane]
            key, inc_spec, draws, inc_s, settings, machines = _profile(lane, receipts, conn)
            median, calls, est = power.pair_cost(conn, lane, incumbent=key, incumbent_spec=inc_spec,
                                                 incumbent_s=inc_s, challenger=challenger,
                                                 settings=settings, machines=machines)
            rates, seen = power.rates_from(draws, split.holdout)
            rho = power.icc([list(draws.values())])
            effect = getattr(a, "effect", None) or power.effect_for(lane)
            tested = adopt.comparisons(conn, lane, split.version)
            alpha = adopt.alpha_for(tested)
            plan = power.plan([rates[c] for c in split.holdout], effect,
                              stochastic=lane in STOCHASTIC_MODALITIES,
                              observed=seen, rho=rho, alpha=alpha,
                              unmeasured=not any(draws.values()))
            missing = set(power.unmeasured(draws, split.holdout))
            measured = [rates[c] for c in split.holdout if c not in missing]
            alone = (power.power(measured, effect, plan.repeat, alpha, rho=plan.rho)
                     if measured else None)
            cases_run = len(set(split.dev) | set(split.holdout))
            more = max(0, plan.cases_needed - len(split.holdout)) if plan.cases_needed else None
            projected = power.projected_seconds(cases_run, plan.repeat, median, calls)
            rows.append({
                "lane": lane, "incumbent": key, "holdout": len(split.holdout),
                "incumbent_keys": [key] if lane in receipts else power.served_keys(conn, lane, inc_spec),
                "cases": cases_run, "too_small": split.too_small,
                "stochastic": plan.stochastic, "observed": seen,
                "rho": plan.rho, "rho_measured": plan.rho_measured,
                "repeat": plan.repeat, "power": round(plan.power, 4),
                "effect": effect, "measured": len(measured),
                "unmeasured": len(missing),
                "power_measured": None if alone is None else round(alone, 4),
                "enough": plan.enough, "effective_cells": plan.cells,
                "mde": plan.mde, "unmeasured_plan": plan.unmeasured,
                "unseen": power.unseen_note(draws),
                "comparisons": tested, "alpha": alpha,
                "cases_needed": plan.cases_needed,
                "more_holdout": more,
                "more_cases": None if more is None else math.ceil(more / holdout.FRACTION),
                "noise_effect": power.noise_for(lane),
                "effect_from": ("given" if getattr(a, "effect", None) else
                                "floor" if effect > power.noise_for(lane) else
                                "measured" if lane in power.EFFECT else "default"),
                "status": _status(plan, more, [rates[c] for c in split.holdout], effect),
                "median_s": median, "calls": calls, "projected_s": projected, "estimate": est,
                "fits_budget": projected is not None and projected <= budget,
                "why": plan.why})
    finally:
        held.close()
    if not want:
        rows += [_absent(lane) for lane in lanes.ALL if lane not in every]
    if getattr(a, "table", False):
        return _table(rows)
    effect = getattr(a, "effect", None)
    wanted = f"+{effect:.2f}" if effect else f"each lane's effect (its rerun noise, never under +{power.MIN_EFFECT:.2f})"
    note(f"power to detect {wanted} per cell at alpha {power._alpha()}, "
         f"target {power.TARGET}, repeat cap {power.CAP}, budget {_hm(budget)}; "
         f"the case is the unit when repeats correlate (rho)")
    for r in rows:
        if not r["cases"]:
            note(f"  {r['lane']:8} {r['status']}")
            continue
        rho = (f"rho {r['rho']:.2f}" + ("" if r["rho_measured"] else " assumed"))
        if r["enough"]:
            head = f"+{r['effect']:.2f}: repeat {r['repeat']} -> power {r['power']:.2f}"
        else:
            head = f"+{r['effect']:.2f}: no repeat reaches {power.TARGET} (best {r['power']:.2f} at repeat {r['repeat']})"
        need = ("saturated" if r["cases_needed"] is None and not r["enough"]
                else f"{r['cases_needed']} holdout needed, "
                     f"{r['more_holdout']} more holdout")
        cost = (f"{r['median_s']:.1f}s/call x {r['calls']} calls, {_hm(r['projected_s'])} at repeat "
                f"{r['repeat']}" + (" fits" if r["fits_budget"] else " over budget")
                if r["median_s"] is not None else "no measured seconds")
        note(f"  {r['lane']:8} holdout {r['holdout']}/{r['cases']}  {rho}  {head}  "
             f"{need}  {cost}  [{r['incumbent'] or 'no incumbent'}, "
             f"{r['observed']} rows]"
             + (f"  alpha {r['alpha']:.4f} after {r['comparisons']} verdict(s) on this holdout"
                if r["comparisons"] else ""))
        if power.challenger_note(r["estimate"] or {}):
            note(f"           {power.challenger_note(r['estimate'])}")
        if r["unseen"]:
            note(f"           {r['unseen']}")
        elif r["unmeasured"]:
            alone = ("nothing measured" if r["power_measured"] is None else
                     f"power {r['power_measured']:.2f} over the {r['measured']} measured")
            note(f"           projected: {r['unmeasured']} of {r['holdout']} holdout "
                 f"unmeasured, drawn from the measured per-case rates; {alone}")
    emit(effect=effect, target=power.TARGET, cap=power.CAP,
         budget_s=budget, lanes=rows)
    return 0


def _status(plan, more, rates, effect) -> str:
    from harness import power
    if plan.enough or more == 0:
        return "enough"
    if more is not None:
        return f"short {more}"
    if not rates or power._cell_odds(rates, effect)[0] <= 0:
        return "saturated"
    return f"over {power.MAX_CASES}"


def _absent(lane: str) -> dict:
    """A lane with no case files in this checkout, such as one whose cases are imported at deploy."""
    return {"lane": lane, "cases": 0, "holdout": 0, "noise_effect": None, "effect": None, "effect_from": "", "rho": None,
            "rho_measured": False, "observed": 0, "power": None, "cases_needed": None,
            "more_holdout": None, "more_cases": None, "status": "no cases here"}


def _table(rows) -> int:
    """One fixed-column row per lane; `soh adopt --json --power` carries the same fields."""
    from harness import power
    head = ("lane", "cases", "holdout", "noise", "effect", "from", "rho", "rows", "power", "needed",
            "more_holdout", "more_cases", "status")
    def cell(v, fmt="{}"):
        return "-" if v is None or v == "" else fmt.format(v)
    lines = [head]
    for r in rows:
        rho = None if r["rho"] is None else f"{r['rho']:.2f}" + ("" if r["rho_measured"] else "?")
        lines.append((r["lane"], str(r["cases"]), str(r["holdout"]), cell(r["noise_effect"], "{:.2f}"),
                      cell(r["effect"], "{:.2f}"),
                      cell(r["effect_from"]), cell(rho), str(r["observed"]), cell(r["power"], "{:.2f}"),
                      cell(r["cases_needed"]), cell(r["more_holdout"]), cell(r["more_cases"]), r["status"]))
    widths = [max(len(line[i]) for line in lines) for i in range(len(head) - 1)]
    for line in lines:
        print("  ".join(c.ljust(w) for c, w in zip(line, widths)) + "  " + line[-1])
    note("noise is the gain the lane's reruns let the gate see; effect is what it powers for, never under "
         f"adopt_min_effect +{power.MIN_EFFECT:.2f} (from floor)")
    note("rho? is assumed until a repeated case measures it; rows 0 means the incumbent's rates are assumed")
    return 0
