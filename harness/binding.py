"""Which knobs are deciding results: per knob and lane, how often the limit it sets was hit (#636).

A knob binds when the limit it names shows up on enough of a lane's recent rows
(a reply cut at the budget, a request past its timeout, a tts clip past the
runaway rate) or of recent inspect and fetch verdicts (a weight over the memory
ceiling, a download over the cap). Past the threshold it is reported in the
loop and the audit instead of silently shaping results.
"""
from __future__ import annotations

import time

from harness import knobs

DAY = 86400.0
#: Days of runs and verdicts a binding count reads.
BINDING_WINDOW_DAYS = 30
#: The share of a lane's rows hitting a knob's limit at which the knob is reported as binding.
BINDING_FRACTION = 0.1
#: Fewer hits than this is never binding, whatever the share.
BINDING_MIN_HITS = 3


def _like(name: str) -> str:
    return name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _machines(sql: str, params: list, column: str, machines) -> str:
    if machines is None:
        return sql
    params.extend(machines)
    return sql + f" AND {column} IN ({', '.join('?' for _ in machines) or 'NULL'})"


def _result_hits(conn, lane: str, name: str, since: float, machines) -> tuple[int, int]:
    """(rows whose hit_limit names `name`, all rows) in `lane`'s runs that ran since `since`."""
    params: list = [_like(name) + ">%", lane, since]
    sql = ("SELECT SUM(CASE WHEN r.hit_limit LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END), COUNT(*) "
           "FROM results r JOIN runs ON r.run_id = runs.id "
           "WHERE runs.lane = ? AND COALESCE(runs.generated_at, runs.recorded_at) >= ?")
    row = conn.execute(_machines(sql, params, "runs.machine_id", machines), params).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def _verdict_hits(conn, name: str, predicate: str, since: float, machines) -> tuple[int, int]:
    """(inspect and fetch verdicts whose until names `name`, all of them) decided since `since`."""
    head = f"limit:{_like(name)}>" if predicate == knobs.LIMIT else f"{_like(name)}:>"
    params: list = [head + "%", since]
    sql = ("SELECT SUM(CASE WHEN until LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END), COUNT(*) "
           "FROM verdicts WHERE tier IN ('inspect', 'fetch') AND decided_at >= ?")
    row = conn.execute(_machines(sql, params, "machine_id", machines), params).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def binds(hits: int, of: int, fraction: float | None = None, least: int | None = None) -> bool:
    fraction = BINDING_FRACTION if fraction is None else fraction
    least = BINDING_MIN_HITS if least is None else least
    return of > 0 and hits >= least and hits / of >= fraction


def count(conn, *, now: float | None = None, machines=None, days: float | None = None) -> list[dict]:
    """One row per knob with a limit and per lane it shapes (lane "" for a lane-free knob)."""
    now = time.time() if now is None else now
    since = now - (BINDING_WINDOW_DAYS if days is None else days) * DAY
    out = []
    for k in knobs.KNOBS.values():
        if not k.limit:
            continue
        for lane in k.lanes or ("",):
            name = k.limit_name(lane)
            if lane:
                hits, of = _result_hits(conn, lane, name, since, machines)
            else:
                hits, of = _verdict_hits(conn, name, k.predicate, since, machines)
            out.append({"knob": k.name, "lane": lane, "limit": name, "value": k.limit_value(lane),
                        "hits": hits, "of": of, "binding": binds(hits, of)})
    return out


def binding(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["binding"]]


def render(rows: list[dict]) -> str:
    """The binding knobs, one line each; a line saying none when none is."""
    found = binding(rows)
    if not found:
        return "  no knob is binding"
    return "\n".join(f"  {r['knob']:16} {r['lane'] or 'any lane':9} {r['limit']} at {r['value']:g}: "
                     f"{r['hits']} of {r['of']} hit it" for r in found)
