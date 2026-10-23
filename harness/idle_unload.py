"""The evidence for the idle unload limits: cold-load seconds from the router's log, and what each limit costs per served model (#1157)."""
from __future__ import annotations

import math
import re
import statistics

#: Days of gateway requests the cost of each limit is read over.
WINDOW_DAYS = 14

_SPAWN = re.compile(r"spawning server instance with name=(\S+) on port (\d+)")
_LOADED = re.compile(r"^\[(\d+)\] (\d+)\.(\d+)\.(\d+)\.\d+ I srv +llama_server: model loaded")


def load_seconds(lines) -> dict[str, list[float]]:
    """Model -> the seconds each child took from its spawn to `model loaded`, read off the child's own uptime stamp."""
    port, out = {}, {}
    for line in lines:
        m = _SPAWN.search(line)
        if m:
            port[m[2]] = m[1]
            continue
        m = _LOADED.match(line)
        if m and m[1] in port:
            out.setdefault(port.pop(m[1]), []).append(int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000)
    return out


def summary(values: list[float]) -> dict:
    v = sorted(values)
    return {"n": len(v), "median_s": round(statistics.median(v), 1), "p90_s": round(v[math.ceil(0.9 * len(v)) - 1], 1),
            "max_s": round(v[-1], 1)}


def uses(conn, since: float, skip=("watchdog", "smoke")) -> dict[str, list[tuple[float, float]]]:
    """Served model -> (start, end) of each gateway request since `since` that the watchdog or a smoke test did not send."""
    from harness import gateway
    out: dict = {}
    marks = ", ".join("?" * len(skip))
    for at, served, total in conn.execute(
            f"SELECT at, served, total_s FROM gateway_requests WHERE at >= ? AND purpose NOT IN ({marks}) ORDER BY at",
            (since, *skip)):
        out.setdefault(gateway.strip_provider(str(served or "")), []).append((float(at) - float(total or 0), float(at)))
    return out


def cost(spans: list[tuple[float, float]], limit: float, days: float) -> dict:
    """Cold loads and idle-but-loaded hours per day had the model been given back `limit` seconds after each request."""
    loads, idle, end = 0, 0.0, None
    for start, stop in spans:
        if end is None or start - end > limit:
            loads += 1
            idle += limit if end is not None else 0.0
        elif start > end:
            idle += start - end
        end = stop if end is None else max(end, stop)
    idle += limit if end is not None else 0.0
    return {"loads_per_day": round(loads / days, 2), "idle_h_per_day": round(idle / 3600 / days, 2)}
