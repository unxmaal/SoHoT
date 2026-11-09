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


def _let(job: dict) -> None:
    from harness import hold
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        hold.let(conn, job["id"])
    finally:
        conn.close()
    job["despite_hold"] = True


def _held(got: list[dict]) -> tuple[str, set]:
    """The benchmark hold's line and the pending jobs it keeps waiting. #1564."""
    from harness import hold
    from harness import memory_store as ms
    from harness import workqueue as wq
    conn = ms.connect()
    try:
        h = hold.active(conn)
        if h is None:
            return "", set()
        return hold.line(h), {j["id"] for j in got if j["state"] == wq.PENDING and hold.held_back(conn, j, h)}
    finally:
        conn.close()


def cmd_jobs(a) -> int:
    """The work queue every caller shares. #353."""
    from harness import workqueue as wq

    rest, title = list(a.rest), a.title
    # REMAINDER swallows options written after the action.
    priority, cwd = a.priority, a.cwd
    night, start = bool(getattr(a, "night", False)), getattr(a, "not_before", "")
    despite = bool(getattr(a, "despite_hold", False))
    resource = getattr(a, "resource", "") or ""
    while rest[:1] in (["--title"], ["--json"], ["--priority"], ["--cwd"], ["--night"],
                       ["--not-before"], ["--despite-hold"], ["--resource"]):
        if rest[0] == "--json":
            common._JSON, rest = True, rest[1:]
        elif rest[0] == "--despite-hold":
            despite, rest = True, rest[1:]
        elif rest[0] == "--night":
            night, rest = True, rest[1:]
        elif len(rest) > 1 and rest[0] == "--resource":
            resource, rest = rest[1], rest[2:]
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
    asks = {"-h", "--help"}
    if rest[:1] and rest[0] in asks or a.action != "add" and asks & set(rest):
        # REMAINDER keeps argparse from seeing --help; only add's command after -- may carry one. #1366.
        a.show_help()
        return 0
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
            if night:
                note("--night is ignored since #1509: a GPU job starts when the contention gate opens (soh gate)")
            job = wq.add(rest, title=a.title, cwd=where, priority=priority,
                         requested_by="cli", not_before=wq.start_at(start), resource=resource)
            if despite:
                _let(job)
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
    from harness import contention, deploy, exclusive, heartbeat
    from harness import memory_store as ms
    got = wq.jobs()
    ok, why = wq.gate()
    loop = heartbeat.summary()
    if loop:
        note(loop["line"])
    conn = ms.connect()
    try:
        gpu = contention.verdict(conn)
        waits = deploy.wait(conn)
    finally:
        conn.close()
    note(f"GPU jobs and deploys: the contention gate is {'open' if gpu['open'] else 'closed'}: {gpu['why']}")
    if waits:
        note(deploy.wait_line(waits))
    later = sum(j["state"] == wq.PENDING and not wq.due(j) for j in got)
    held, waiting = _held(got)
    if held:
        note(f"{held}; {len(waiting)} measurement job(s) wait for soh hold release")
    note(f"{'a job is running' if wq.running() else 'nothing running'}; "
         f"{sum(j['state'] == wq.PENDING for j in got)} pending"
         f"{f' ({later} waiting for their start time)' if later else ''}; next job "
         f"{'may start' if ok else 'waits'}: {why}")
    shown = ([j for j in got if j["state"] == wq.RUNNING] + wq.order(
        [j for j in got if j["state"] == wq.PENDING])
             + [j for j in got if j["state"] in (wq.DONE, wq.PAUSED, wq.FAILED, wq.CANCELLED)])
    locks = exclusive.holders()
    loose = held_locks(got, locks)
    for j in shown:
        rc = "" if j["rc"] is None else f" rc={j['rc']}"
        pri = int(j.get("priority") or 0)
        at = (f"from {j['not_before'].replace('T', ' ')[:16]} "
              if j["state"] == wq.PENDING and not wq.due(j) else "")
        lock = f" [holds the {j['lock']} lock]" if j.get("lock") else ""
        lock += " [held: benchmarks]" if j["id"] in waiting else ""
        note(f"  {j['id']}  {j['state']:8}{rc:7}  p{pri:<3} {wq.needs(j):7} {at}{j['title']}{lock}")
    for h in loose:
        note(f"  {h['lock']} lock held by {exclusive.describe(h)}, outside the queue")
    from harness import item_lease
    conn = ms.connect()
    try:
        leases = item_lease.live(conn)
    finally:
        conn.close()
    for h in leases:
        note(f"  {item_lease.line(h)}")
    emit(running=wq.running(), gate_open=ok, why=why, jobs=got, loop=loop, contention=gpu, deploy_wait=waits, locks=locks,
         hold=held, held=sorted(waiting), leases=leases)
    return 0
