"""`soh adopt`: make a measured run a lane's winner, or say what power each lane's gate needs."""
from __future__ import annotations

import json
from pathlib import Path

from harness import lanes, paths
from harness.commands.common import emit, err, note
from harness.commands import measure as measure_cmd


def _run_name(run: Path) -> str:
    """A run under the runs dir by its directory name, anything else by path."""
    try:
        return str(run.resolve().relative_to((paths.home() / "runs").resolve()))
    except ValueError:
        return str(run)


def cmd_adopt(a) -> int:
    """The discovery loop's paired measure-and-adopt, for a named challenger."""
    if getattr(a, "power", False):
        return cmd_power(a)
    if not a.lane or not a.challenger:
        return err("adopt needs --lane and --challenger, or --power")
    lane = lanes.canonical(a.lane)
    if lane not in lanes.ALL:
        return err(f"unknown lane {a.lane!r}; known: {', '.join(lanes.ALL)}")
    return measure_cmd._measure_and_adopt(a, {"name": a.challenger, "lane": lane})


def _receipts(files) -> dict[str, list[list[dict]]]:
    """lane -> the row lists of each receipt file given."""
    out: dict[str, list[list[dict]]] = {}
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        lane = lanes.canonical((data.get("receipt") or {}).get("modality") or "")
        out.setdefault(lane, []).append(list(data.get("rows") or []))
    return out


def _row(r: dict) -> dict:
    return {"candidate": r.get("candidate"), "case_id": r.get("case_id"),
            "passed": r.get("passed"), "seconds": r.get("seconds")}


def _profile(lane: str, receipts: dict, conn) -> tuple[str, dict, float | None]:
    """(incumbent key, its draws per case, its median seconds) from receipts or the store."""
    from harness import adopt, candidates, power, screen, winners
    served = adopt.default_for(lane, winners.typed().get(lane, ""))
    spec = (screen.candidate_for(lane, served) or served) if served else ""
    try:
        key = candidates.key_of(spec) if spec else ""
    except Exception:  # noqa: BLE001
        key = ""
    if lane in receipts:
        sets = [[_row(r) for r in rows] for rows in receipts[lane]]
        key = power.control_of(sets, prefer=[k for k in (key, spec, served) if k])
        draws, median = power.draws_from([r for rows in sets for r in rows], key)
        return key, draws, median
    key = key or spec
    draws, median = power.incumbent_profile(conn, lane, key) if key else ({}, None)
    return key, draws, median


def _hm(seconds) -> str:
    if seconds is None:
        return "time unknown"
    m = int(round(seconds / 60))
    return f"~{m // 60}h{m % 60:02d}m" if m >= 60 else f"~{max(m, 1)}m"


def cmd_power(a) -> int:
    """Per lane: the repeat and holdout size power 0.8 needs, and what that run would cost. #591."""
    from evals.run import STOCHASTIC_MODALITIES
    from harness import holdout, power
    from harness import memory_store as ms

    receipts = _receipts(getattr(a, "receipt", None) or [])
    every = holdout.splits()
    want = lanes.canonical(a.lane) if a.lane else ""
    if want and want not in every:
        return err(f"no cases for lane {a.lane!r}; lanes with cases: "
                   f"{', '.join(sorted(every))}")
    budget = float(getattr(a, "power_budget_min", None) or power.BUDGET_MIN) * 60
    rows = []
    conn = ms.connect()
    try:
        for lane in [want] if want else sorted(every):
            split = every[lane]
            key, draws, median = _profile(lane, receipts, conn)
            rates, seen = power.rates_from(draws, split.holdout)
            rho = power.icc([list(draws.values())])
            effect = getattr(a, "effect", None) or power.effect_for(lane)
            plan = power.plan([rates[c] for c in split.holdout], effect,
                              stochastic=lane in STOCHASTIC_MODALITIES,
                              observed=seen, rho=rho)
            cases_run = len(set(split.dev) | set(split.holdout))
            projected = power.projected_seconds(cases_run, plan.repeat, median)
            rows.append({
                "lane": lane, "incumbent": key, "holdout": len(split.holdout),
                "cases": cases_run, "too_small": split.too_small,
                "stochastic": plan.stochastic, "observed": seen,
                "rho": plan.rho, "rho_measured": plan.rho_measured,
                "repeat": plan.repeat, "power": round(plan.power, 4),
                "enough": plan.enough, "effective_cells": plan.cells,
                "cases_needed": plan.cases_needed,
                "more_holdout": (max(0, plan.cases_needed - len(split.holdout))
                                 if plan.cases_needed else None),
                "median_s": median, "projected_s": projected,
                "fits_budget": projected is not None and projected <= budget,
                "why": plan.why})
    finally:
        conn.close()
    effect = getattr(a, "effect", None) or power.DEFAULT_EFFECT
    note(f"power to detect +{effect:.2f} per cell at alpha {power._alpha()}, "
         f"target {power.TARGET}, repeat cap {power.CAP}, budget {_hm(budget)}; "
         f"the case is the unit when repeats correlate (rho)")
    for r in rows:
        rho = (f"rho {r['rho']:.2f}" + ("" if r["rho_measured"] else " assumed"))
        if r["enough"]:
            head = f"repeat {r['repeat']} -> power {r['power']:.2f}"
        else:
            head = f"no repeat reaches {power.TARGET} (best {r['power']:.2f} at repeat {r['repeat']})"
        need = ("saturated" if r["cases_needed"] is None and not r["enough"]
                else f"{r['cases_needed']} holdout needed, "
                     f"{r['more_holdout']} more holdout")
        cost = (f"{r['median_s']:.1f}s/case, {_hm(r['projected_s'])} at repeat "
                f"{r['repeat']}" + (" fits" if r["fits_budget"] else " over budget")
                if r["median_s"] is not None else "no measured seconds")
        note(f"  {r['lane']:8} holdout {r['holdout']}/{r['cases']}  {rho}  {head}  "
             f"{need}  {cost}  [{r['incumbent'] or 'no incumbent'}, "
             f"{r['observed']} rows]")
    emit(effect=effect, target=power.TARGET, cap=power.CAP,
         budget_s=budget, lanes=rows)
    return 0
