"""`soh weedout-replay`: stored paired runs and planted challengers through today's looks and the weed-out order. #1439."""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass

from harness import adopt, holdout, looks, power, weedout
from harness.paired import UNJUDGED

def scenarios() -> dict:
    """Planted challengers by their shift in mean pass rate."""
    return {"equal": 0.0, "+5": 0.05, "+10": 0.10, "-5": -0.05}


@dataclass(frozen=True)
class Outcome:
    adopt: bool
    how: str
    cases: int
    seconds: float


def lane_rows(conn, lane: str) -> list[dict]:
    """Every measure row of the lane, with its run, case and draw."""
    out = []
    for r in conn.execute("SELECT x.run_id, x.seq, x.candidate, x.case_id, x.passed, x.seconds, x.metrics, "
                          "x.failure_class FROM results x JOIN runs u ON u.id = x.run_id "
                          "WHERE u.lane = ? AND u.tier = 'measure'", ((lane or "").strip().lower(),)):
        d = dict(r)
        try:
            d["metrics"] = json.loads(d["metrics"] or "{}")
        except ValueError:
            d["metrics"] = {}
        d["seconds"] = float(d["seconds"] or 0.0)
        d["base"] = holdout.base_id(d["case_id"])
        d["draw"] = power.draw(d, lane)
        d["judged"] = bool(d["passed"]) or d["failure_class"] not in UNJUDGED
        out.append(d)
    return out


def paired(conn, lane: str, rows: list[dict]) -> list[dict]:
    """The lane's two-candidate measure runs: incumbent from the verdict on the run, else the more-measured side."""
    by: dict[int, set] = {}
    for r in rows:
        by.setdefault(r["run_id"], set()).add(r["candidate"])
    seen: dict[str, int] = {}
    for cands in by.values():
        if len(cands) == 2:
            for c in cands:
                seen[c] = seen.get(c, 0) + 1
    out = []
    for rid, cands in sorted(by.items()):
        if len(cands) != 2:
            continue
        run = conn.execute("SELECT split, repeat_count FROM runs WHERE id = ?", (rid,)).fetchone()
        v = conn.execute("SELECT c.receipt_key FROM verdicts v LEFT JOIN candidates c ON c.id = v.candidate_id "
                         "WHERE v.run_id = ? AND v.tier = 'adopt' ORDER BY v.id DESC", (rid,)).fetchone()
        ch = v[0] if v is not None and v[0] in cands else None
        inc = (cands - {ch}).pop() if ch else sorted(cands, key=lambda c: (-seen[c], c))[0]
        out.append({"run": rid, "split": run[0] or "", "repeat": int(run[1] or 1), "inc": inc,
                    "ch": ch or (cands - {inc}).pop(), "stored": v is not None})
    return out


def _plan(cases, rates: dict, secs: dict, effect: float, repeat: int, ordered: bool) -> dict:
    plan = {"repeat": repeat, "cells": len(cases) * repeat, "cases": len(cases), "effect": effect,
            "odds": power._cell_odds([rates[c] for c in cases], effect)}
    if ordered:
        plan.update(weedout.planned(cases, rates, secs, effect))
    return plan


def _history(rows: list[dict], inc: str, cases, skip_run: int | None = None):
    """(rates, seconds) per case from the incumbent's rows, less one run: a run never orders itself."""
    draws: dict[str, list[int]] = {}
    secs: dict[str, list[float]] = {}
    for r in rows:
        if r["candidate"] != inc or r["run_id"] == skip_run:
            continue
        secs.setdefault(r["base"], []).append(r["seconds"])
        if r["judged"]:
            draws.setdefault(r["base"], []).append(r["draw"])
    return power.rates_from(draws, list(cases))[0], {c: statistics.fmean(v) for c, v in secs.items()}


def walk(lane: str, seq: list[dict], cases, inc: str, ch: str, plan: dict, alpha: float,
         step: float | None = None) -> Outcome:
    """Rows in run order with a look each `step` seconds, as measure takes them; the end is the full gate."""
    step = looks.LOOK_INTERVAL_S if step is None else step
    split = holdout.Split(lane, (), tuple(cases), False)
    taken: list[dict] = []
    elapsed, nxt = 0.0, step
    for i, r in enumerate(seq):
        elapsed += r["seconds"]
        if not step or elapsed < nxt or i == len(seq) - 1:
            continue
        while nxt <= elapsed:
            nxt += step
        lk, v = looks.look(seq[:i + 1], lane=lane, inc_key=inc, ch_key=ch, split=split, plan=plan, alpha=alpha,
                           spent_before=taken[-1]["spent"] if taken else 0.0, n=len(taken) + 1)
        taken.append(lk.as_dict())
        if v is not None:
            return Outcome(v.adopt, lk.decision, len({q["base"] for q in seq[:i + 1]}), elapsed)
    spent = taken[-1]["spent"] if taken else 0.0
    v = adopt.decide(lane, {"candidate": inc}, {"candidate": ch}, seq, split=split, alpha=alpha - spent)
    return Outcome(v.adopt, "final", len({q["base"] for q in seq}), elapsed)


def in_order(seq: list[dict], ids) -> list[dict]:
    at = {c: i for i, c in enumerate(ids)}
    from harness.paired import repeat_index
    return sorted(seq, key=lambda r: (repeat_index(r["case_id"]), at.get(r["base"], len(at)), r["seq"],
                                      r["candidate"]))


def replay(conn, lane: str, alpha: float = adopt.ALPHA) -> list[dict]:
    """Each stored paired run: the full gate, today's looks in stored order, and the weed-out order's looks."""
    rows = lane_rows(conn, lane)
    effect = power.effect_for(lane)
    held = set(holdout.for_lane(lane).holdout)
    out = []
    for x in paired(conn, lane, rows):
        mine = sorted((r for r in rows if r["run_id"] == x["run"]), key=lambda r: r["seq"])
        cases = list(dict.fromkeys(r["base"] for r in mine))
        if x["split"] in ("holdout", "all"):
            cases = [c for c in cases if c in held] or cases
        mine = [r for r in mine if r["base"] in set(cases)]
        rates, secs = _history([r for r in rows if r["candidate"] != x["ch"]], x["inc"], cases, x["run"])
        split = holdout.Split(lane, (), tuple(cases), False)
        full = adopt.decide(lane, {"candidate": x["inc"]}, {"candidate": x["ch"]}, mine, split=split, alpha=alpha)
        today = walk(lane, mine, cases, x["inc"], x["ch"], _plan(cases, rates, secs, effect, x["repeat"], False), alpha)
        plan = _plan(cases, rates, secs, effect, x["repeat"], True)
        weed = walk(lane, in_order(mine, plan["order"]), cases, x["inc"], x["ch"], plan, alpha)
        out.append({**x, "cases": len(cases), "seconds": sum(r["seconds"] for r in mine), "full": full.adopt,
                    "today": today, "weedout": weed})
    return out


def _planted(rate: dict, shift: float, cases) -> tuple[dict, dict]:
    """(gain, loss) chance per failing or passing challenger draw that moves its mean pass rate by `shift`."""
    n = len(cases)
    if shift > 0:
        room = sum(1 - rate[c] for c in cases)
        k = min(1.0, shift * n / room) if room else 0.0
        return {c: k for c in cases}, {c: 0.0 for c in cases}
    if shift < 0:
        mass = sum(rate[c] for c in cases)
        k = min(1.0, -shift * n / mass) if mass else 0.0
        return {c: 0.0 for c in cases}, {c: k for c in cases}
    return {c: 0.0 for c in cases}, {c: 0.0 for c in cases}


def simulate(conn, lane: str, inc: str, reps: int = 200, blocks: int = 4, alpha: float = adopt.ALPHA,
             seed: int = 1439) -> dict:
    """Planted challengers on the lane's holdout: the incumbent's runs split in halves, one half orders and plans,
    the other is resampled for both sides; per scenario, P(adopt) and mean cases and hours per rule."""
    rng = random.Random(seed)
    held = set(holdout.for_lane(lane).holdout)
    rows = [r for r in lane_rows(conn, lane) if r["base"] in held]
    cases = sorted({r["base"] for r in rows if r["candidate"] == inc})
    runs = sorted({r["run_id"] for r in rows if r["candidate"] == inc})
    effect = power.effect_for(lane)
    acc: dict = {s: {k: [] for k in ("full", "today", "weedout")} for s in scenarios()}
    for _ in range(blocks):
        half = set(rng.sample(runs, max(1, len(runs) // 2))) if len(runs) > 1 else set(runs)
        rates, secs = _history([r for r in rows if r["run_id"] not in half], inc, cases)
        pool: dict[str, list] = {}
        for r in rows:
            if r["candidate"] == inc and r["judged"] and (r["run_id"] in half or len(runs) < 2):
                pool.setdefault(r["base"], []).append((r["draw"], r["seconds"]))
        got = [c for c in cases if pool.get(c)]
        mean = {c: statistics.fmean(d for d, _ in pool[c]) for c in got}
        today_plan = _plan(got, rates, secs, effect, 1, False)
        weed_plan = _plan(got, rates, secs, effect, 1, True)
        for name, shift in scenarios().items():
            gain, loss = _planted(mean, shift, got)
            for _ in range(reps):
                seq = []
                for i, c in enumerate(got):
                    xd, xs = rng.choice(pool[c])
                    yd, ys = rng.choice(pool[c])
                    if yd == 0 and rng.random() < gain[c]:
                        yd = 1
                    elif yd == 1 and rng.random() < loss[c]:
                        yd = 0
                    seq.append({"candidate": "inc", "case_id": c, "base": c, "passed": xd, "seconds": xs,
                                "metrics": {}, "seq": 2 * i})
                    seq.append({"candidate": "ch", "case_id": c, "base": c, "passed": yd, "seconds": ys,
                                "metrics": {}, "seq": 2 * i + 1})
                full = adopt.decide(lane, {"candidate": "inc"}, {"candidate": "ch"}, seq,
                                    split=holdout.Split(lane, (), tuple(got), False), alpha=alpha)
                today = walk(lane, seq, got, "inc", "ch", today_plan, alpha)
                weed = walk(lane, in_order(seq, weed_plan["order"]), got, "inc", "ch", weed_plan, alpha)
                for rule, o in (("full", Outcome(full.adopt, "final", len(got), sum(r["seconds"] for r in seq))),
                                ("today", today), ("weedout", weed)):
                    acc[name][rule].append((o, o.adopt == full.adopt))
    return {s: {rule: {"adopt": statistics.fmean(o.adopt for o, _ in got),
                       "agree": statistics.fmean(a for _, a in got),
                       "cases": statistics.fmean(o.cases for o, _ in got),
                       "hours": statistics.fmean(o.seconds for o, _ in got) / 3600,
                       "futility": statistics.fmean(o.how == "futility" for o, _ in got)}
                for rule, got in per.items()} for s, per in acc.items()}


def replay_lines(got: list[dict]) -> list[str]:
    v = lambda o: f"{'adopt' if o.adopt else 'keep'} {o.how} {o.cases} {o.seconds / 3600:.2f}h"
    lines = [f"run {x['run']}{'' if x['stored'] else ' (no verdict row)'}: {x['cases']} cases "
             f"{x['seconds'] / 3600:.2f}h, full {'adopt' if x['full'] else 'keep'}; today {v(x['today'])}; "
             f"weed-out {v(x['weedout'])}{'' if x['weedout'].adopt == x['full'] else '  DIFFERS'}" for x in got]
    n = len(got)
    same = sum(1 for x in got if x["weedout"].adopt == x["full"])
    wrong = sum(1 for x in got if x["weedout"].adopt and not x["full"])
    lines.append(f"{n} paired run(s): weed-out same verdict {same}/{n}, adopts where full kept {wrong}; cases "
                 f"full/today/weed-out {sum(x['cases'] for x in got)}/{sum(x['today'].cases for x in got)}/"
                 f"{sum(x['weedout'].cases for x in got)}; hours {sum(x['seconds'] for x in got) / 3600:.1f}/"
                 f"{sum(x['today'].seconds for x in got) / 3600:.1f}/{sum(x['weedout'].seconds for x in got) / 3600:.1f}")
    return lines


def simulate_lines(got: dict) -> list[str]:
    lines = []
    for s, per in got.items():
        lines.append(f"{s}: " + "; ".join(
            f"{rule} adopt {m['adopt']:.3f} same {m['agree']:.3f} cases {m['cases']:.1f} hours {m['hours']:.2f}"
            for rule, m in per.items()))
    return lines
