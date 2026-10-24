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
#: workqueue requested_by for a knob sweep's jobs (harness.sweeps.REQUESTED_BY).
SWEEP = "sweep"
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
    # A sweep's runs are the experiment at other settings, not the knob as it stands. #636.
    sql = ("SELECT SUM(CASE WHEN r.hit_limit LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END), COUNT(*) "
           "FROM results r JOIN runs ON r.run_id = runs.id LEFT JOIN jobs ON jobs.id = runs.job_id "
           "WHERE runs.lane = ? AND COALESCE(runs.generated_at, runs.recorded_at) >= ? "
           f"AND COALESCE(jobs.requested_by, '') != '{SWEEP}'")
    row = conn.execute(_machines(sql, params, "runs.machine_id", machines), params).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def _conversions(conn, lane: str, name: str, value, since: float, machines) -> dict:
    """Of the replies cut at `value` in `lane`, how many passed with more room, per model whose recent rows hit `name`. #1124."""
    from harness import convertible
    params: list = [_like(name) + ">%", lane, since]
    sql = ("SELECT COALESCE(c.spec, r.candidate) FROM results r JOIN runs ON r.run_id = runs.id "
           "LEFT JOIN candidates c ON c.id = r.candidate_id "
           "WHERE r.hit_limit LIKE ? ESCAPE '\\' AND runs.lane = ? AND COALESCE(runs.generated_at, runs.recorded_at) >= ?")
    sql = _machines(sql, params, "runs.machine_id", machines) + " ORDER BY COALESCE(runs.generated_at, runs.recorded_at) DESC"
    newest: dict = {}
    for row in conn.execute(sql, params):
        newest.setdefault(convertible.base_of(row[0]), row[0])
    got = {"converted": 0, "cuts": 0, "where": []}
    for spec in newest.values():
        s = convertible.best(convertible.stored(conn, lane, spec, machines), spec, int(value))
        if s:
            got["converted"] += s["passed"]
            got["cuts"] += s["cut"]
            got["where"].append(s["where"])
    return got


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
            row = {"knob": k.name, "lane": lane, "limit": name, "value": k.limit_value(lane),
                   "hits": hits, "of": of, "binding": binds(hits, of)}
            if lane and hits and k.receipt == "max_tokens":
                row.update(_conversions(conn, lane, name, row["value"], since, machines))
            out.append(row)
    return out + _cut_rows(conn, since, machines)


def _cut_rows(conn, since: float, machines) -> list[dict]:
    """One row per registered knob a limit_cuts row names, at the largest value it cut at: each cut is the knob deciding something. #1087."""
    from harness import cuts
    top = cuts.highest(conn, since, machines)
    return [{"knob": name, "lane": "", "limit": f"cut:{name}", "value": top.get(name), "hits": hits, "of": hits,
             "binding": binds(hits, hits), "source": "cut"}
            for name, hits in sorted(cuts.count(conn, since, machines).items()) if name in knobs.KNOBS]


def binding(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["binding"]]


def render(rows: list[dict]) -> str:
    """The binding knobs, one line each; a line saying none when none is."""
    found = binding(rows)
    if not found:
        return "  no knob is binding"
    return "\n".join(f"  {r['knob']:16} {r['lane'] or 'any lane':9} {r['limit']} at {_value(r['value'])}: "
                     f"{_converted(r)}{_hits(r)}" for r in found)


def _value(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _hits(r: dict) -> str:
    return f"{r['hits']} cut(s)" if r.get("source") == "cut" else f"{r['hits']} of {r['of']} hit it"


def _converted(r: dict) -> str:
    """A cut binds only if it passes with more room, so a reply budget's line leads with those. #1124."""
    if "cuts" not in r:
        return ""
    if not r["cuts"]:
        return "no cut reply was given more room; "
    return f"{r['converted']} of {r['cuts']} cuts converted ({', '.join(r['where'])}); "
