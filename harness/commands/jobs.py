"""`soh jobs`: the work queue every caller shares. #353."""
from __future__ import annotations

from harness.commands import common
from harness.commands.common import emit, err, note


def _task_row(t) -> dict:
    return {"lane": t.lane, "candidate": t.candidate, "cost_s": t.cost_s,
            "skip": t.skip, "why": t.why}


def cmd_jobs(a) -> int:
    """The work queue every caller shares. #353."""
    from harness import workqueue as wq

    rest, title = list(a.rest), a.title
    # REMAINDER swallows options written after the action.
    priority, cwd = a.priority, a.cwd
    while rest[:1] in (["--title"], ["--json"], ["--priority"], ["--cwd"]):
        if rest[0] == "--json":
            common._JSON, rest = True, rest[1:]
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
            job = wq.add(rest, title=a.title, cwd=where, priority=priority,
                         requested_by="cli")
            note(f"queued {job['id']}: {job['title']}")
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
    from harness import heartbeat
    got = wq.jobs()
    ok, why = wq.gate()
    loop = heartbeat.summary()
    if loop:
        note(loop["line"])
    note(f"{'a job is running' if wq.running() else 'nothing running'}; "
         f"{sum(j['state'] == wq.PENDING for j in got)} pending; next job "
         f"{'may start' if ok else 'waits'}: {why}")
    shown = ([j for j in got if j["state"] == wq.RUNNING] + wq.order(
        [j for j in got if j["state"] == wq.PENDING])
             + [j for j in got if j["state"] in (wq.DONE, wq.FAILED, wq.CANCELLED)])
    for j in shown:
        rc = "" if j["rc"] is None else f" rc={j['rc']}"
        pri = int(j.get("priority") or 0)
        note(f"  {j['id']}  {j['state']:8}{rc:7}  p{pri:<3} {j['title']}")
    emit(running=wq.running(), gate_open=ok, why=why, jobs=got, loop=loop)
    return 0
