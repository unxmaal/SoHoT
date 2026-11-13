"""A queued job's next state once its process exits or its worker is gone, and the runner's recovery of jobs left running. #1728, #1902."""
from __future__ import annotations

import json
import time

from harness import job_claim, job_procs, job_state as js, resources


def _settle_cancelled(job: dict, how: str = "") -> bool:
    """Move a running job cancelled; False when its worker recorded its exit first, which then stands. #1728."""
    from harness import workqueue as wq
    said = {"term": "stopped on request", "kill": "killed after the grace period",
            "gone": "had already exited"}.get(how, "stopped")
    with wq._store() as c:
        took = js.move(c, job["id"], js.RUNNING, js.CANCELLED, js.CANCEL,
                       f"cancelled by soh jobs cancel at {time.strftime(wq._STAMP)}; {said}", finished_at=time.time())
        c.commit()
    return took


def _lease_lost(job: dict, why: str) -> None:
    """Stop a job whose lease is gone or about to lapse, so no second job takes its class under it. #1728, #1732."""
    from harness import executors, workqueue as wq
    print(f"{time.strftime('%H:%M:%S')} job {job['id']}: lease lost ({why}); stopping it", flush=True)
    pid = job_claim.await_pid(job["id"], wq.CANCEL_GRACE_S)
    if pid is not None:
        executors.for_job(job).stop(pid, wq.CANCEL_GRACE_S)


def _settle_exit(job: dict, rc, conn=None) -> bool:
    """Move a job whose process exited, as job_state.exit_move chooses from its flags and rc; True when a handed-off deploy stays running. #1728."""
    from evals import watch
    from harness import contention, deploy, queue_pause, workqueue as wq
    flags = job_procs._flags(job["id"])
    handed = job.get("kind") == resources.DEPLOY and rc == deploy.HANDED_OFF
    with wq._store(conn) as c:
        contended = rc == watch.PAUSED and js.DEPLOY_FLAG not in flags and contention.paused_for(c, job)
        to, why = js.exit_move(rc, flags, handed, contended)
        if to == js.RUNNING:
            return True
        argv = _item_argv(c, job) if why == js.NEXT_ITEM else None
        if why == js.NEXT_ITEM and argv is None:
            to, why = js.exit_move(rc, flags - {js.ITEM_FLAG}, handed, contended)
        if why == js.DEPLOY_STOP:
            queue_pause._repend_stopped(c, job)
        elif why in (js.DEPLOY_PAUSE, js.CONTENTION_PAUSE):
            _repend(c, job, why)
        elif why == js.NEXT_ITEM:
            _next_item(c, job, argv)
        else:
            note = f"cancelled by soh jobs cancel at {time.strftime(wq._STAMP)}; stopped" if why == js.CANCEL else None
            if why == js.CHECKPOINTED:
                from harness import paused_jobs
                why, note = paused_jobs.cause(c, job)
            js.move(c, job["id"], js.RUNNING, to, why, note, rc=rc, finished_at=wq._epoch(job["finished"]))
            c.commit()
    job_procs._clear_flags(job["id"])
    return False


def resume_argv(argv: list, out) -> list[str]:
    """argv without any --out or --resume, then --out `out` --resume."""
    got, skip = [], False
    for a in map(str, argv):
        if skip:
            skip = False
        elif a == "--out":
            skip = True
        elif a != "--resume" and not a.startswith("--out="):
            got.append(a)
    return [*got, "--out", str(out), "--resume"]


def _resumed(c, job: dict) -> list | None:
    """The argv that resumes an eval job from its stored run, or None when it is no eval or stored none. #1509."""
    from harness import runs
    if confirms(job):
        return list(job["argv"])
    run = runs.for_job(c, int(job["id"]))
    if "evals.run" not in [str(a) for a in job["argv"]] or run is None:
        return None
    return resume_argv(job["argv"], runs.run_dir(run["path"]))


def confirms(job: dict) -> bool:
    """Whether a job is `soh adopt --confirm`, whose own argv resumes the newest unfinished run of its pair. #1357, #1675."""
    argv = [str(a) for a in job.get("argv") or []]
    return resources._verb(argv) == "adopt" and "--confirm" in argv


def _item_argv(c, job: dict) -> list | None:
    """The argv of a job's next item: its eval resumed from its stored run, or its own; None when an eval stored none. #1618."""
    from evals import run
    return _resumed(c, job) if run.queued_args(job["argv"]) is not None else list(job["argv"])


def _next_item(c, job: dict, argv: list) -> bool:
    """A job that stopped at its item's end waits again for its next item, resumed where it stopped. #1618."""
    from harness import workqueue as wq
    took = (wq._epoch(job.get("finished")) or time.time()) - (wq._epoch(job.get("started")) or time.time())
    moved = js.move(c, job["id"], js.RUNNING, js.PENDING, js.NEXT_ITEM,
                    f"item ended after {took:.0f}s of a planned {wq.ITEM_S:.0f}s; the next item waits its turn",
                    finished_at=None, rc=job.get("rc"), argv=json.dumps(argv))
    c.commit()
    if moved:
        from harness import cuts
        cuts.cut("queue_item", f"job {wq.label(job['id'])}: an item ended after {took:.0f}s; the next waits its turn", kept=1)
    return moved


def _repend(c, job: dict, why: str) -> bool:
    """A job paused for contention or a deploy waits again to resume where it stopped, unless it queued its own continuation. #1509, #1672."""
    from harness import machine_scope, workqueue as wq
    here, mine = machine_scope.where("jobs.twin", job.get("machine_id"))
    resumed = _resumed(c, job)
    # A job that stored a run is carried on only by a job resuming that run, never a fresh one with its argv. #1774.
    carries = [str(a) for a in (resumed or job["argv"])]
    twin = c.execute(f"SELECT id FROM jobs WHERE argv = ? AND state = ? AND id != ? AND {here}",
                     (json.dumps(carries), js.PENDING, int(job["id"]), *mine)).fetchone()
    if twin is not None:
        moved = js.move(c, job["id"], js.RUNNING, js.PAUSED, js.CONTINUED, f"paused; job {wq.label(twin[0])} continues it",
                        rc=job.get("rc"), finished_at=wq._epoch(job.get("finished")))
        c.commit()
        return moved
    argv = resumed or list(job["argv"])
    note = ("paused for a deploy at {}; resumes after it" if why == js.DEPLOY_PAUSE else
            "paused for contention at {}; resumes when the contention gate opens").format(job.get("finished"))
    moved = js.move(c, job["id"], js.RUNNING, js.PENDING, why, note, finished_at=None, rc=job.get("rc"),
                    argv=json.dumps(argv))
    c.commit()
    return moved


def _settle_gone(c, job: dict) -> None:
    """A running job whose worker and process are gone, as job_state.gone_move chooses: an eval that stored a run, or a confirm, waits again to resume it, else it failed."""
    from harness import executors, queue_pause, workqueue as wq
    if (exited := executors.exit_record(job_procs._pid_file(job["id"]))) is not None:  # recorded before its worker died. #1758
        _settle_exit({**job, "rc": exited[0], "finished": wq._iso(exited[1])}, exited[0], conn=c)
        return
    flags = job_procs._flags(job["id"])
    argv = None if flags & {js.CANCEL_FLAG, js.STOP_FLAG} else _resumed(c, job)
    to, why = js.gone_move(flags, argv is not None)
    if why == js.DEPLOY_STOP:
        queue_pause._repend_stopped(c, job)
    elif why == js.WORKER_GONE:
        js.move(c, job["id"], js.RUNNING, js.PENDING, why, "its worker went away; resumes from its stored run",
                started_at=None, argv=json.dumps(argv))
    elif why == js.CANCEL:
        js.move(c, job["id"], js.RUNNING, js.CANCELLED, why, "cancelled by soh jobs cancel; its worker went away "
                "before it recorded the exit", finished_at=time.time())
    else:
        js.move(c, job["id"], js.RUNNING, to, why, "interrupted; add it again to retry")
    c.commit()
    job_procs._clear_flags(job["id"])


def _recover() -> list[dict]:
    """At the runner's start each running job here lost its worker: those whose process runs on, to watch; the rest settled. #1558."""
    from harness import queue_pause, workqueue as wq
    queue_pause.settle_deploys()
    left = []
    with wq._store() as c:
        where, args = wq._claimed(c)
        for job in wq._select(c, f"WHERE state = ? AND kind != ? AND {where}", (js.RUNNING, resources.DEPLOY, *args)):
            if job_procs._pid_of(job["id"]) is not None:
                left.append(job)
            elif not job_claim.starting(job["id"]):
                _settle_gone(c, job)
    return left


def _watch_left(job: dict, poll: float | None = None) -> None:
    """Lease a job a gone worker left running until its process exits, then settle it. #1558."""
    from harness import workqueue as wq
    poll = wq.WATCH_S if poll is None else poll
    pid = job_procs._pid_of(job["id"])
    if pid is not None:
        with wq.leased(job, pid=pid):
            while job_procs.alive(pid):
                time.sleep(poll)
    job_procs._pid_file(job["id"]).unlink(missing_ok=True)
    with wq._store() as c:
        _settle_gone(c, job)
