"""`soh jobs`: the work queue every caller shares. #353."""
from __future__ import annotations

from harness.commands import common
from harness.commands.common import emit, err, note


def _task_row(t) -> dict:
    return {"lane": t.lane, "candidate": t.candidate, "cost_s": t.cost_s,
            "skip": t.skip, "why": t.why}


def held_locks(jobs: list[dict], holders=None) -> list[dict]:
    """Set each running job's "lock" ("gpu", "cloud" or "") from the lock holders; returns those no running job owns. #1135."""
    from harness import exclusive
    from harness import workqueue as wq
    holders = exclusive.holders() if holders is None else holders
    ids = {j["id"] for j in jobs if j["state"] == wq.RUNNING}
    by_job, loose = {}, []
    for h in holders:
        key = str(h.get("job") or "").strip()
        job = wq.label(key) if key.isdigit() else ""
        if job in ids:
            by_job.setdefault(job, h["lock"])
        else:
            loose.append(h)
    for j in jobs:
        if j["state"] == wq.RUNNING:
            j["lock"] = by_job.get(j["id"], "")
    return loose


def cmd_jobs(a) -> int:
    """The work queue every caller shares. #353."""
    from harness import workqueue as wq

    rest, title = list(a.rest), a.title
    # REMAINDER swallows options written after the action.
    priority, cwd = a.priority, a.cwd
    night, start = bool(getattr(a, "night", False)), getattr(a, "not_before", "")
    while rest[:1] in (["--title"], ["--json"], ["--priority"], ["--cwd"], ["--night"],
                       ["--not-before"]):
        if rest[0] == "--json":
            common._JSON, rest = True, rest[1:]
        elif rest[0] == "--night":
            night, rest = True, rest[1:]
        elif len(rest) > 1 and rest[0] == "--not-before":
            start, rest = rest[1], rest[2:]
        elif len(rest) > 1 and rest[0] == "--title":
            title, rest = rest[1], rest[2:]
        elif len(rest) > 1 and rest[0] == "--cwd":
            cwd, rest = rest[1], rest[2:]
        elif len(rest) > 1:
            try:
                priority = int(rest[1])
            except ValueError:
                return err(f"--priority takes a number, not {rest[1]!r}")
            rest = rest[2:]
        else:
            break
    if rest[:1] == ["--"]:
        rest = rest[1:]
    elif a.action != "add" and "--json" in rest:
        # Only `add` carries a command of its own; elsewhere a flag is a flag.
        common._JSON, rest = True, [x for x in rest if x != "--json"]
    a.title = title
    try:
        if a.action == "add":
            import os
            where = wq.queue_cwd(os.getcwd(), wq.deployed(), explicit=cwd)
            not_before, gated = wq.start_with_night(start, night)
            job = wq.add(rest, title=a.title, cwd=where, priority=priority,
                         requested_by="cli", not_before=not_before, night=gated)
            after = f" (not before {job['not_before']})" if job["not_before"] else ""
            note(f"queued {job['id']}{after}: {job['title']}")
            emit(job=job)
            return 0
        if a.action == "priority":
            if len(rest) != 2:
                return err("priority needs a job id and a number: soh jobs priority 0005 10")
            try:
                job = wq.set_priority(rest[0], int(rest[1]))
            except ValueError as exc:
                return err(str(exc))
            note(f"{job['id']} priority {job['priority']}: {job['title']}")
            emit(job=job)
            return 0
        if a.action == "cancel":
            if not rest:
                return err("cancel needs a job id")
            job = wq.cancel(rest[0])
            note(f"cancelled {job['id']}: {job['title']}")
            emit(job=job)
            return 0
    except ValueError as exc:
        return err(str(exc))
    if a.action in ("pause", "resume"):
        (wq.pause if a.action == "pause" else wq.resume)()
        ok, why = wq.gate()
        note(f"{a.action}d; next job {'may start' if ok else 'waits'}: {why}")
        emit(paused=wq.paused(), gate_open=ok, why=why)
        return 0
    from harness import day_clear, exclusive, heartbeat
    got = wq.jobs()
    ok, why = wq.gate()
    loop = heartbeat.summary()
    if loop:
        note(loop["line"])
    clearance = wq.cleared()
    if clearance:
        note(f"{day_clear.line(clearance)}; the watchdog's day limits are off and night-start jobs may run now")
    later = sum(j["state"] == wq.PENDING and not wq.due(j, cleared=clearance is not None) for j in got)
    note(f"{'a job is running' if wq.running() else 'nothing running'}; "
         f"{sum(j['state'] == wq.PENDING for j in got)} pending"
         f"{f' ({later} waiting for their start time)' if later else ''}; next job "
         f"{'may start' if ok else 'waits'}: {why}")
    shown = ([j for j in got if j["state"] == wq.RUNNING] + wq.order(
        [j for j in got if j["state"] == wq.PENDING])
             + [j for j in got if j["state"] in (wq.DONE, wq.FAILED, wq.CANCELLED)])
    locks = exclusive.holders()
    loose = held_locks(got, locks)
    for j in shown:
        rc = "" if j["rc"] is None else f" rc={j['rc']}"
        pri = int(j.get("priority") or 0)
        at = (f"from {j['not_before'].replace('T', ' ')[:16]} "
              if j["state"] == wq.PENDING and not wq.due(j, cleared=clearance is not None) else "")
        lock = f" [holds the {j['lock']} lock]" if j.get("lock") else ""
        note(f"  {j['id']}  {j['state']:8}{rc:7}  p{pri:<3} {at}{j['title']}{lock}")
    for h in loose:
        note(f"  {h['lock']} lock held by {exclusive.describe(h)}, outside the queue")
    emit(running=wq.running(), gate_open=ok, why=why, jobs=got, loop=loop, clearance=clearance, locks=locks)
    return 0
