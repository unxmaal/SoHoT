"""A paused queue job leaves paused by a named move: resumed when its cause clears, superseded, expired, or failed as needing a person (#1764)."""
from __future__ import annotations

import json
import time

from harness import job_state as js

EXPIRY_S = 86400.0
#: What a pause file or watchdog pause names when memory paused the job: the watchdog's criteria and evals.run's deferral.
MEMORY_CAUSES = ("memory", "memory_stuck", "memory_headroom")
#: Job states that carry a paused job's work on; a failed or cancelled later job does not.
_CARRIES = (js.PENDING, js.RUNNING, js.DONE, js.PAUSED)


def _said(conn, job: dict) -> str:
    """What paused a job that exited paused: a memory criterion the watchdog paused it for, else any it did, else its run's pause file."""
    from harness import watchdog
    from harness import workqueue as wq
    started = wq._epoch(job.get("started")) or 0.0
    criteria = sorted({r[0] for r in conn.execute(
        "SELECT criterion FROM watchdog_actions WHERE job_id = ? AND action = ? AND dry_run = 0 AND at >= ?",
        (int(job["id"]), watchdog.PAUSE, started))})
    if criteria:
        return next((c for c in criteria if c in MEMORY_CAUSES), criteria[0])
    from evals import watch
    from harness import runs
    run = runs.for_job(conn, int(job["id"]))
    return watch.pause_reason(runs.run_dir(run["path"])) if run is not None else ""


def ends(reason: str) -> str:
    """What moves a job paused for `reason` on, as its note says."""
    if reason == js.MEMORY_PAUSE:
        return "resumes when memory pressure is back to normal"
    if reason == js.QUEUE_PAUSE:
        return "resumes when the queue is resumed (soh jobs resume)"
    return "nothing clears it on its own"


def cause(conn, job: dict) -> tuple[str, str]:
    """(reason, note) a job that exited paused with nothing re-pending it is recorded paused with."""
    from harness import workqueue as wq
    said = _said(conn, job)
    if said in MEMORY_CAUSES:
        reason = js.MEMORY_PAUSE
    elif wq.paused():
        reason, said = js.QUEUE_PAUSE, said or "the queue pause"
    else:
        reason = js.CHECKPOINTED
    return reason, (f"paused by {said or 'a request'} at {job.get('finished')}; {ends(reason)}, "
                    f"else it fails expired after {EXPIRY_S:.0f}s")


def resume_argv(conn, job: dict) -> list[str] | None:
    """The argv that resumes a paused job where it stopped, or None when it has none."""
    from harness import resources
    from harness import workqueue as wq
    argv = [str(a) for a in job.get("argv") or []]
    if wq.confirms(job):
        return argv
    if "evals.run" in argv:
        return wq._resumed(conn, job)
    if (resources._verb(argv) == "adopt" and "--challenger" in argv
            and not {"--power", "--from-measurement", "--dry-run"} & set(argv)):
        return argv
    return None


def _owned(conn, job_id: int) -> bool:
    """Whether an open reverification or knob sweep owns this paused job and queues its continuation itself."""
    from harness import sweeps
    if conn.execute("SELECT 1 FROM reverifications WHERE job_id = ? AND outcome = ''", (job_id,)).fetchone():
        return True
    return any(int(j) == job_id for (got,) in conn.execute("SELECT jobs FROM knob_sweeps WHERE outcome = ?",
                                                           (sweeps.OPEN,)) for _, j in json.loads(got or "[]"))


def _twin(conn, job: dict, argv: list | None) -> int | None:
    """A later job that carries this paused job's work on: its own argv or its resume argv."""
    said = {json.dumps([str(a) for a in job.get("argv") or []])} | ({json.dumps(argv)} if argv else set())
    marks, states = ",".join("?" * len(said)), ",".join("?" * len(_CARRIES))
    row = conn.execute(f"SELECT MIN(id) FROM jobs WHERE id > ? AND argv IN ({marks}) AND state IN ({states})",
                       (int(job["id"]), *sorted(said), *_CARRIES)).fetchone()
    return None if row is None or row[0] is None else int(row[0])


def cleared(reason: str, pressure=None) -> bool:
    """Whether the cause of a pause for `reason` has cleared now."""
    from harness import workqueue as wq
    if reason == js.MEMORY_PAUSE:
        from harness import pressure as pr
        return not (pressure or pr.sample)().alarming
    if reason == js.QUEUE_PAUSE:
        return not wq.paused()
    return False


def _alert(message: str) -> None:
    from harness import monitor
    try:
        monitor.alert("service", {"MONIT_SERVICE": "queue", "MONIT_DESCRIPTION": message})
    except (OSError, ValueError) as exc:
        print(f"queue alert failed: {exc}", flush=True)


def decide(conn, job: dict, now: float, pressure=None, alert=None) -> dict | None:
    """Move one paused job out of paused when its cause cleared, another job carries it, it has no resume path or it expired; None when it stays."""
    from harness import cuts
    from harness import workqueue as wq
    jid, name = int(job["id"]), wq.label(job["id"])
    if _owned(conn, jid):
        return None
    argv = resume_argv(conn, job)
    twin = _twin(conn, job, argv)
    reason = job.get("reason") or js.CHECKPOINTED
    if twin is not None:
        to, why, note, cols = js.CANCELLED, js.SUPERSEDED, f"paused; job {wq.label(twin)} carries it on", {}
    elif argv is None:
        to, why, cols = js.FAILED, js.NEEDS_OWNER, {}
        note = f"paused ({reason}) with no resume path: needs a person to requeue or cancel it"
    elif cleared(reason, pressure):
        to, why, cols = js.PENDING, js.RESUMED, {"argv": json.dumps(argv), "finished_at": None}
        note = f"resumed at {time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))}: its {reason} cleared"
    elif now - (wq._epoch(job.get("finished")) or now) >= EXPIRY_S:
        to, why, cols = js.FAILED, js.EXPIRED, {}
        note = f"paused ({reason}) and its cause did not clear in {EXPIRY_S:.0f}s; failed, its run kept"
    else:
        return None
    moved = js.move(conn, jid, js.PAUSED, to, why, note, **cols)
    conn.commit()
    if not moved:
        return None
    line = f"job {name} {to} ({why}): {note}"
    if why == js.EXPIRED:
        cuts.cut("job_pause_expiry", f"job {name}: paused past its bound", dropped=1, conn=conn)
    if to == js.FAILED:
        (alert or _alert)(line)
    return {"id": name, "state": to, "reason": why, "line": line}


def settle(conn, now: float | None = None, pressure=None, alert=None) -> list[dict]:
    """Each worker turn: decide every paused job this machine claimed, oldest first."""
    from harness import workqueue as wq
    now = time.time() if now is None else now
    where, args = wq._claimed(conn)
    sampled: list = []

    def once():
        if not sampled:
            from harness import pressure as pr
            sampled.append((pressure or pr.sample)())
        return sampled[0]
    got = [decide(conn, j, now, once, alert) for j in wq._select(conn, f"WHERE state = ? AND {where}",
                                                                   (js.PAUSED, *args))]
    return [g for g in got if g is not None]


def turn(now: float) -> list[dict]:
    """The worker's turn: settle, logged rather than raised. #1764."""
    from harness import workqueue as wq
    try:
        with wq._store() as c:
            got = settle(c, now)
    except Exception as exc:  # noqa: BLE001 - a paused-job check must not stop the worker, on any store
        print(f"{time.strftime('%H:%M:%S')} paused job check failed: {exc}", flush=True)
        return []
    for g in got:
        print(f"{time.strftime('%H:%M:%S')} {g['line']}", flush=True)
    return got
