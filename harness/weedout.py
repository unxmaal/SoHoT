"""A paired run's case order: expected discordant cells per incumbent second, from the incumbent's draws alone. #1439."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

#: Seconds added to every case's price when ordering by expected discordant cells per second.
ADD_S = 1.0
ORDER_FILE = "order.json"


def score(rate: float, effect: float) -> float:
    """Expected discordant cells per cell on a case the incumbent passes at `rate`, under the plan's effect."""
    q = min(1.0, rate + effect)
    return (1 - rate) * q + rate * (1 - q)


def order(cases, rates: dict, seconds: dict, effect: float) -> list[str]:
    """Cases by expected discordant cells per incumbent second, highest first; an untimed case costs the typical one."""
    at = {c: i for i, c in enumerate(cases)}
    timed = [seconds[c] for c in cases if seconds.get(c) is not None]
    typical = statistics.fmean(timed) if timed else 0.0
    cost = {c: (typical if seconds.get(c) is None else seconds[c]) + ADD_S for c in cases}
    return sorted(cases, key=lambda c: (-score(rates[c], effect) / cost[c], at[c]))


def seconds_of(conn, lane: str, inc_spec: str) -> dict[str, float]:
    """case -> the served incumbent's mean seconds over its stored rows, store-wide."""
    from harness import holdout, power
    by: dict[str, list[float]] = {}
    for r in power._served_rows(conn, lane, inc_spec)[1]:
        if r["seconds"] is not None:
            by.setdefault(holdout.base_id(r["case_id"]), []).append(float(r["seconds"]))
    return {c: statistics.fmean(v) for c, v in by.items()}


def planned(cases, rates: dict, seconds: dict, effect: float) -> dict:
    """The order and per-case rates a plan carries, so every look and every resume reads the same ones."""
    cases = list(cases)
    return {"order": tuple(order(cases, rates, seconds, effect)), "rates": {c: float(rates[c]) for c in cases}}


def write(out, ids) -> Path:
    path = Path(out) / ORDER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(ids)), encoding="utf-8")
    return path


def left(rows, inc_key: str, ch_key: str, cases, repeat: int) -> dict[str, int]:
    """case -> cells it still lacks, a cell being a (case, repeat) both candidates have a row for."""
    from harness import holdout
    have: dict[str, dict[str, set]] = {}
    for r in rows or ():
        who = r.get("candidate")
        if who in (inc_key, ch_key):
            have.setdefault(who, {}).setdefault(holdout.base_id(r.get("case_id")), set()).add(r.get("case_id"))
    mine, theirs = have.get(inc_key, {}), have.get(ch_key, {})
    return {c: max(0, repeat - len(mine.get(c, set()) & theirs.get(c, set()))) for c in cases
            if len(mine.get(c, set()) & theirs.get(c, set())) < repeat}


def rest_odds(rates: dict, missing: dict[str, int], effect: float) -> tuple[float, float]:
    """Per-cell P(gained), P(lost) over the cells still to run, each case at its own rate."""
    from harness import power
    cells = sum(missing.values())
    if not cells:
        return 0.0, 0.0
    gain = lose = 0.0
    for c, n in missing.items():
        g, lo = power._cell_odds([rates.get(c, power.UNSEEN)], effect)
        gain += n * g
        lose += n * lo
    return gain / cells, lose / cells
