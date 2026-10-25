"""An engine's wall clock per case: its slowest finished case on this machine times a margin, else its own ceiling (#708)."""
from __future__ import annotations

import math
import sys

from harness import reasons

#: The derived timeout is this many times the slowest finished case; 0 keeps every engine's own ceiling.
MARGIN = 3.0
#: Finished cases an engine needs on this machine before its own ceiling gives way to the measured one.
MIN_CASES = 10
#: Seconds no derived timeout goes below: a process start on a loaded machine, whatever the engine measured.
FLOOR_S = 60.0
#: Cases per candidate per run that, cut under a derived clock, are rerun once at the engine's ceiling (#1256).
RERUNS = 1
#: The margins `soh knobs engine-timeouts` backtests.
MARGINS = (2.0, 3.0, 5.0, 10.0)
#: Failure classes of a case the engine generated an output for; a load failure or a crash measured no generation (#1256).
GENERATED = ("", reasons.CONTENT_FAILED, *reasons.CUT)


def key(candidate: str) -> str:
    """The receipt-key prefix an engine's rows are stored under: mflux, h3, trace, upscale-seedvr2."""
    return candidate.split("/", 1)[0]


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _rows(conn, lane: str = "", engine: str = "", machines=None) -> list[tuple]:
    """(lane, engine key, machine_id, seconds) of generated cases, oldest first; a timed-out case measured our clock."""
    sql = ("SELECT r.lane, x.candidate, r.machine_id, x.seconds FROM results x JOIN runs r ON r.id = x.run_id "
           f"WHERE x.seconds > 0 AND COALESCE(x.failure_class, '') IN ({','.join('?' * len(GENERATED))})")
    args: list = list(GENERATED)
    if lane:
        sql += " AND r.lane = ?"
        args.append(lane)
    if engine:
        sql += " AND x.candidate LIKE ? ESCAPE '\\'"
        args.append(_like(engine) + "/%")
    if machines is not None:
        ids = tuple(machines)
        if not ids:
            return []
        sql += f" AND r.machine_id IN ({','.join('?' * len(ids))})"
        args.extend(ids)
    sql += " ORDER BY COALESCE(r.generated_at, r.recorded_at), r.id, x.seq"
    return [(row[0], key(row[1]), row[2], float(row[3])) for row in conn.execute(sql, args)]


def derive(cases: int, slowest: float, ceiling: float, margin: float | None = None) -> float:
    """margin x the slowest finished case, never under FLOOR_S, once MIN_CASES are measured; else `ceiling`."""
    margin = MARGIN if margin is None else margin
    if not margin or cases < MIN_CASES:
        return float(ceiling)
    return float(max(FLOOR_S, math.ceil(margin * slowest)))


def basis(conn, lane: str, candidate: str, ceiling: float, machines=None) -> dict:
    """The timeout an engine runs at here and what it came from, for the runner and the receipt."""
    from harness import runs
    machines = runs.here(conn) if machines is None else machines
    found = [s for *_, s in _rows(conn, lane, key(candidate), machines)]
    slowest = max(found, default=0.0)
    measured = bool(MARGIN) and len(found) >= MIN_CASES
    return {"seconds": derive(len(found), slowest, ceiling), "from": "measured" if measured else "ceiling",
            "cases": len(found),
            "slowest": round(slowest, 3), "margin": MARGIN, "ceiling": float(ceiling)}


def runners(runner):
    """`runner` and every base a method wraps."""
    while runner is not None:
        yield runner
        runner = getattr(runner, "base", None)


def apply(conn, runner, lane: str) -> dict:
    """Set the derived timeout on every engine runner `runner` holds; {} for a runner with no engine clock."""
    got = {}
    for r in runners(runner):
        ceiling = getattr(r, "ceiling", None)
        if ceiling is None:
            continue
        got = basis(conn, lane, r.candidate, ceiling)
        r.timeout = got["seconds"]
        r.derived = got["from"] == "measured"
    return got


def for_runner(runner, lane: str) -> dict:
    """apply() on this machine's store; a store that cannot be read leaves the engine's ceiling."""
    if not any(getattr(r, "ceiling", None) is not None for r in runners(runner)):
        return {}
    from harness import memory_store as ms
    try:
        conn = ms.connect()
        try:
            got = apply(conn, runner, lane)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - no measurement means the engine's own ceiling
        print(f"  engine timeout: the stored rows could not be read ({exc}); its ceiling stands", file=sys.stderr)
        return {}
    print(f"  engine timeout: {said(got)}", flush=True)
    return got


def for_engine(engine, lane: str = "") -> float:
    """The seconds `engine` runs at on this machine, for a deadline set before a runner exists."""
    from harness import memory_store as ms
    try:
        conn = ms.connect()
        try:
            return basis(conn, lane or engine.modality, engine.name, engine.timeout)["seconds"]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - no measurement means the engine's own ceiling
        return float(engine.timeout)


def for_cases(engine, cases: int, lane: str = "") -> float:
    """The longest `cases` of `engine` should take here: each at its clock, plus RERUNS of them rerun at its ceiling (#1256)."""
    clock = for_engine(engine, lane)
    if clock >= float(engine.timeout):
        return cases * clock
    return cases * clock + min(RERUNS, cases) * float(engine.timeout)


def reran(runner) -> dict:
    """{"reran": each rerun at the ceiling, "ended_at": the clock the run ended on} for the receipt; {} if none ran (#1256)."""
    for r in runners(runner):
        if getattr(r, "reran", None):
            return {"reran": [dict(e) for e in r.reran], "ended_at": float(r.timeout)}
    return {}


def said(b: dict) -> str:
    if b.get("from") == "measured":
        return (f"{b['seconds']:g}s = {b['margin']:g} x the slowest of {b['cases']} finished case(s) here "
                f"({b['slowest']:g}s); its ceiling was {b['ceiling']:g}s")
    return f"{b.get('seconds', 0):g}s, the engine's ceiling ({b.get('cases', 0)} finished case(s) here, {MIN_CASES} needed)"


def is_engine(k: str) -> bool:
    """Whether rows under this key prefix ran through an engine process with a clock: a process engine, a chain stage or a trace."""
    from harness import engines
    from evals.runners.chain import STAGES
    return k in engines.names() or k in STAGES or k == "trace" or k.startswith("trace-")


def backtest(conn, margins=MARGINS, machines=None) -> list[dict]:
    """Per lane, engine and machine: the slowest case, and how many finished cases each margin would have cut had it been set from the cases before them."""
    groups: dict = {}
    for lane, eng, mid, s in _rows(conn, machines=machines):
        if not is_engine(eng):
            continue
        g = groups.setdefault((lane, eng, mid), {"lane": lane, "engine": eng, "machine_id": mid, "cases": 0,
                                                 "slowest": 0.0, "cut": {m: 0 for m in margins}})
        if g["cases"] >= MIN_CASES:
            for m in margins:
                if s > max(FLOOR_S, math.ceil(m * g["slowest"])):
                    g["cut"][m] += 1
        g["cases"] += 1
        g["slowest"] = max(g["slowest"], s)
    for g in groups.values():
        g["seconds"] = derive(g["cases"], g["slowest"], 0.0) or None
    return sorted(groups.values(), key=lambda g: (g["lane"], g["engine"], g["machine_id"] or 0))
