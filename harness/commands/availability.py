"""`soh availability`: per text lane, the share of watchdog probes it answered and each outage with its bounds. #924."""
from __future__ import annotations

import time

from harness.availability import hm, incident_line
from harness.commands.common import emit, note


def render(r: dict) -> list[str]:
    out = [f"since {hm(r['since'])}, target {r['target']:.0%} per lane"]
    if not r["lanes"]:
        out.append("no lane_probes rows in the window: the watchdog has not probed here")
    for lane, u in r["lanes"].items():
        rate = "n/a" if u["rate"] is None else f"{u['rate']:.2%}"
        flag = "" if u["rate"] is None or u["rate"] >= r["target"] else "  BELOW TARGET"
        out.append(f"{lane:<8} {rate:>7} of {u['judged']} judged (up {u['up']}, down {u['down']}, slow {u['slow']}); "
                   f"skipped {u['skipped']}; incidents {u['incidents']}{' (one open)' if u['open'] else ''}{flag}")
    for i in r["incidents"]:
        out.append(f"  incident {incident_line(i)}")
    return out


def cmd_availability(a) -> int:
    from harness import availability, morning
    now = time.time()
    since = now - float(a.days) * 86400
    conn = morning.snapshot()
    try:
        if not availability.has_table(conn):
            r = {"since": since, "until": now, "target": availability.TARGET, "lanes": {}, "incidents": []}
        else:
            r = availability.report(conn, since, now, machine_id=availability.here(conn))
    finally:
        conn.close()
    for ln in render(r):
        note(ln)
    emit(**r)
    return 0
