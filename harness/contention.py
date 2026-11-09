"""The contention gate in place of the night rule: GPU work runs when no hold, normal memory and idle served lanes. #1509."""
from __future__ import annotations

import time

from harness import purpose

#: Seconds the served lanes must go with no client request before a GPU job or a deploy starts. #1509.
IDLE_S = 600.0
#: Request purposes that are a client being served; SoHoT's own evals, smoke, probes, sweeps and pipelines are not.
SERVED = (purpose.WORK, purpose.UNKNOWN)
#: The watchdog criterion that pauses a running GPU job for contention.
CRITERION = "contention"
#: Who queues a job a client waits on (an MCP image or video): it is serving, never held or paused as batch work.
SERVING = ("mcp",)
#: Seconds a deploy waits on memory pressure past normal before it starts anyway; it loads no model, it restarts them. #1672.
DEPLOY_PRESSURE_S = 1800.0
#: Seconds a deploy may wait, for any reason, before one alert names why. #1672.
DEPLOY_ALERT_S = 10800.0

_said = ""


def requests(conn, since: float) -> list[tuple[str, float]]:
    """(alias, when it ended) of each client request the gateway answered that was running at or after `since`."""
    from harness import usage
    marks = ",".join("?" * len(SERVED))
    return [(str(r["alias"] or "?"), float(r["ended"])) for r in conn.execute(
        f"SELECT alias, {usage.ENDED_SQL} AS ended FROM gateway_requests "
        f"WHERE {usage.ENDED_SQL} >= ? AND purpose IN ({marks})", (since, *SERVED))]


def served(conn, since: float) -> dict:
    """Client requests the gateway answered that were running at or after `since`, by alias."""
    got = requests(conn, since)
    by: dict = {}
    for alias, _ in got:
        by[alias] = by.get(alias, 0) + 1
    return {"requests": len(got), "by_alias": by, "last": max((t for _, t in got), default=None)}


def reading(conn, now: float) -> dict:
    """What the watchdog judges a running job by: the gpu hold and the requests of the last IDLE_S."""
    from harness import hold
    return {"hold": hold.active(conn, now, hold.GPU), "requests": requests(conn, now - IDLE_S)}


def pressure_until(since: float) -> str:
    """The clock time a deploy waiting since `since` stops waiting on memory pressure. #1672."""
    return time.strftime("%H:%M", time.localtime(since + DEPLOY_PRESSURE_S))


def verdict(conn, now: float | None = None, sample=None, since: float | None = None) -> dict:
    """Whether a GPU job, or with `since` a deploy waiting since then, may start now, why, and each signal read."""
    from harness import cuts, hold, pressure
    now = time.time() if now is None else now
    p = (sample or pressure.sample)()
    hold_now = hold.active(conn, now, hold.GPU) if conn is not None else hold._legacy(now)
    use = served(conn, now - IDLE_S) if conn is not None else {"requests": None, "by_alias": {}, "last": None}
    got = {"open": False, "pressure_level": p.level, "served": use["requests"], "by_alias": use["by_alias"],
           "last_served": use["last"], "hold": hold_now, "idle_s": IDLE_S}
    if hold_now is not None:
        return {**got, "why": f"held by the owner: {hold_now['said']} ({hold.RELEASE} {hold.GPU})"}
    waived = p.alarming and since is not None and now - since >= DEPLOY_PRESSURE_S
    if p.alarming and not waived:
        bound = f"; a deploy waits on it until {pressure_until(since)}" if since is not None else ""
        return {**got, "why": f"memory pressure level {p.level}, not normal{bound}"}
    if use["requests"]:
        cuts.cut("contention_idle", "GPU job starts while the served lanes were in use", dropped=1, conn=conn)
        ago = round(now - use["last"]) if use["last"] is not None else None
        return {**got, "why": f"served lanes in use: {use['requests']} client request(s) in the last "
                              f"{IDLE_S:.0f} s, the latest {ago} s ago"}
    if use["requests"] is None:
        return {**got, "why": "the served lanes could not be read: no store"}
    level = "normal" if p.level is not None else "unknown"
    if waived:
        level = (f"level {p.level}, but the deploy has waited past its {DEPLOY_PRESSURE_S:.0f} s bound on it "
                 f"(queued {time.strftime('%H:%M', time.localtime(since))})")
    return {**got, "open": True, "why": f"memory pressure {level}, served lanes idle {IDLE_S:.0f} s, no hold"}


def gate(conn, now: float | None = None, sample=None, say=None, since: float | None = None) -> tuple[bool, str]:
    """(open, why) for a GPU job or a deploy; says each change of decision, which is the queue's log of them."""
    global _said
    v = verdict(conn, now, sample, since)
    if v["why"] != _said:
        line = f"{time.strftime('%H:%M:%S')} contention gate {'open' if v['open'] else 'closed'}: {v['why']}"
        say(line) if say else print(line, flush=True)
        _said = v["why"]
    return v["open"], v["why"]


def batch(job: dict) -> bool:
    """Whether the gate holds this job: everything but what a client is waiting on."""
    return (job.get("requested_by") or "") not in SERVING


def paused_for(conn, job: dict) -> bool:
    """Whether the watchdog paused this queued job for contention since it last started."""
    from harness import workqueue
    started = workqueue._epoch(job.get("started")) or 0.0
    return conn.execute("SELECT 1 FROM watchdog_actions WHERE criterion = ? AND subject = ? AND action = 'pause' "
                        "AND dry_run = 0 AND at >= ? LIMIT 1",
                        (CRITERION, f"job {workqueue.label(job['id'])}", started)).fetchone() is not None
