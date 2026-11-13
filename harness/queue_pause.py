"""The queue's pause flag, a deploy's hold on the queue for its install, and the worker's deploy turn. #1675, #1902."""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from harness import job_claim, job_procs, job_settle, job_state as js, paths, queue_hold, resources


def _pause_flag() -> Path:
    from harness import workqueue as wq
    return wq.root() / "paused"


def paused() -> bool:
    return _pause_flag().exists()


def pause(why: str = "", holder: int | None = None) -> None:
    """Pause the queue; a holder pid makes it a hold that ends with that process, not an owner's pause. #1760."""
    _pause_flag().write_text(queue_hold.text(why, holder), encoding="utf-8")


def resume() -> None:
    _pause_flag().unlink(missing_ok=True)


def _held_flag() -> Path:
    from harness import workqueue as wq
    return wq.root() / "paused.deploy"


def paused_for_deploy(environ=None) -> bool:
    """Whether a due deploy asked this queued job to pause, so the worker re-pends it rather than it queueing a continuation. #1675."""
    from harness import workqueue as wq
    key = wq._key((environ if environ is not None else os.environ).get(wq.JOB_ENV, ""))
    return key is not None and job_procs._deploy_flag(key).exists()


def hold_for_deploy(grace: float | None = None, stop=None, tree=None, stop_rest=None, holder=None) -> list[str]:
    """LH_DEPLOY_DURING_SWEEP: pause the queue for the install, then stop each job running here, every process under it, to resume after. #1675."""
    from harness import executors, sweep_guard, workqueue as wq
    grace = wq.CANCEL_GRACE_S if grace is None else grace
    said = queue_hold.lift([_held_flag(), _pause_flag()])
    if not paused():
        # The marker goes down before the pause it marks, so no death between them leaves an owner-looking pause. #1754.
        text = queue_hold.text(f"held for a deploy by pid {holder or os.getpid()}", holder)
        _held_flag().write_text(text, encoding="utf-8")
        _pause_flag().write_text(text, encoding="utf-8")
        said.append("queue held for the deploy; it is released when the install ends")
    elif _held_flag().exists():
        said.append("queue already held for a deploy; it is released when the install ends")
    else:
        said.append("queue was already paused by its owner and stays paused after the deploy (soh jobs resume)")
    for job in wq.running_here():
        if job["kind"] == resources.DEPLOY:
            continue
        # A job its worker claimed just before the pause starts in a moment; it is stopped with the rest. #1895.
        pid = job_claim.await_pid(job["id"], grace)
        if pid is None:
            continue
        # Snapshot first: a process measure started in its own session is not in the job's group.
        procs = (tree or job_procs._tree)(pid)
        under = [{"pid": p} for p, _ in procs if p != pid]
        job_procs._stop_flag(job["id"]).write_text(json.dumps({"at": time.strftime(wq._STAMP), "argv": _stopped_argv(
            job, {p for p, _ in procs})}), encoding="utf-8")
        how = (stop or executors.for_job(job).stop)(pid, grace)
        rest = [r for r in under if job_procs.alive(r["pid"])]
        left = (stop_rest or sweep_guard.stop)(rest, grace=grace, alive=job_procs.alive) if rest else []
        with wq._store() as c:
            _repend_stopped(c, job)
        tail = f"; pid(s) {', '.join(map(str, left))} outlived SIGKILL" if left else ""
        said.append(f"job {job['id']} stopped for the deploy ({how}); it resumes after it{tail}")
    return said


def _repend_stopped(c, job: dict) -> bool:
    """A running job a deploy stopped waits again, resumed where it stopped when it can be; False when its exit was recorded first. #1675."""
    from harness import workqueue as wq
    try:
        said = json.loads(job_procs._stop_flag(job["id"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        said = {}
    argv = (said.get("argv") if isinstance(said, dict) else None) or job_settle._resumed(c, job) or list(job["argv"])
    moved = js.move(c, job["id"], js.RUNNING, js.PENDING, js.DEPLOY_STOP,
                    f"stopped for a deploy at {time.strftime(wq._STAMP)}; resumes after it",
                    started_at=None, finished_at=None, argv=json.dumps(argv))
    c.commit()
    return moved


def release_for_deploy() -> str:
    """Lift the hold hold_for_deploy set, whatever the install did; an owner's pause, or one set since, stays. #1675."""
    return queue_hold.release(_held_flag(), _pause_flag())


def _stopped_argv(job: dict, pids: set) -> list[str] | None:
    """The argv that resumes a bare eval job from the one run its processes were writing, or None. #1675."""
    from harness import run_state, sweep_guard
    if "evals.run" not in [str(a) for a in job["argv"]]:
        return None
    outs = set()
    for path in sorted(paths.runs().glob(f"*/{sweep_guard.PROGRESS}")):
        got = run_state.of(path.parent, alive=lambda pid, pgid, started="": sweep_guard._pid(pid) in pids)
        if got.name in run_state.LIVE and sweep_guard._pid(got.progress.get("pid")) in pids:
            outs.add(path.parent)
    return job_settle.resume_argv(job["argv"], outs.pop()) if len(outs) == 1 else None


def preempt_for_deploy(now: float | None = None, evals=None, signal_=None) -> list[str]:
    """A due deploy asks each running measurement job's evals here to pause at their next case; the job then waits to resume. #1672."""
    from harness import deploy, hold, workqueue as wq
    sig = signal_ if signal_ is not None else getattr(signal, "SIGUSR1", None)
    if sig is None or deploy.paused():
        return []
    with wq._store() as c:
        if not any(j["kind"] == resources.DEPLOY and wq.due(j, now) for j in wq.pending(c)):
            return []
        busy = [j for j in wq.running_here(c) if hold.measurement(j)]
    said = []
    for job in busy:
        pid, flag = job_procs._pid_of(job["id"]), job_procs._deploy_flag(job["id"])
        asked = set(flag.read_text(encoding="utf-8").split()) if flag.exists() else set()
        fresh = [p for p in (evals or job_procs._evals_in)(pid) if str(p) not in asked] if pid is not None else []
        for p in fresh:
            try:
                os.kill(p, sig)
            except OSError as exc:
                said.append(f"job {job['id']}: eval {p} not asked to pause: {exc}")
                continue
            asked.add(str(p))
            said.append(f"job {job['id']}: eval {p} asked to pause at its next case for the pending deploy")
        if asked:
            flag.write_text(" ".join(sorted(asked)), encoding="utf-8")
    return said + _ask_loop(sig, evals or job_procs._evals_in)


def _ask_loop(sig, evals) -> list[str]:
    """The scheduled sweep yields at its next checkpoint, its evals pause after their case, and it goes on on the new release. #1675."""
    from harness import heartbeat, sweep_guard, workqueue as wq
    beat = heartbeat.read() or {}
    if beat.get("state") != heartbeat.RUNNING or not beat.get(heartbeat.YIELDS):
        return []
    said = []
    for r in sweep_guard.running(paths.home()):
        if r["what"] != "discover loop" or r["pid"] != beat.get("pid"):
            continue
        # Asked each turn: an eval the loop starts before its checkpoint is asked too.
        for p in [r["pid"], *evals(r["pid"])]:
            try:
                os.kill(p, sig)
            except OSError as exc:
                said.append(f"discover loop {r['pid']}: {p} not asked to yield: {exc}")
        flag = wq.root() / "loop-yield"
        if not flag.exists() or flag.read_text(encoding="utf-8") != str(r["pid"]):
            flag.write_text(str(r["pid"]), encoding="utf-8")
            said.append(f"discover loop {r['pid']} asked to yield at its next checkpoint for the pending deploy")
    return said


def _settle_alerted() -> Path:
    from harness import workqueue as wq
    return wq.root() / "deploy-settle-alerted"


def settle_deploys(alert=None) -> list | None:
    """deploy.settle, logged rather than raised; None when it failed, alerted once per distinct failure. #1506, #1783."""
    import sqlite3

    from harness import deploy
    try:
        got = deploy.settle()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        said = f"deploy settle failed, so no deploy moves until it reads: {type(exc).__name__}: {exc}"[:500]
        print(f"{time.strftime('%H:%M:%S')} {said}", flush=True)
        try:
            before = _settle_alerted().read_text(encoding="utf-8")
        except OSError:
            before = ""
        if before != said:
            _settle_alerted().write_text(said, encoding="utf-8")
            (alert or deploy._alert_here)(said)
        return None
    _settle_alerted().unlink(missing_ok=True)
    for d in got:
        print(f"{time.strftime('%H:%M:%S')} settled {d}", flush=True)
    return got


def watch_deploys(now: float | None = None) -> dict | None:
    """deploy.watch_wait, logged rather than raised: a pending deploy waiting too long alerts once. #1672."""
    from harness import deploy
    try:
        got = deploy.watch_wait(now)
    except Exception as exc:  # noqa: BLE001 - a check of the wait must not stop the worker, on any store
        print(f"{time.strftime('%H:%M:%S')} deploy wait check failed: {exc}", flush=True)
        return None
    if got is not None:
        print(f"{time.strftime('%H:%M:%S')} alerted: {deploy.wait_line(got)}", flush=True)
    return got


def deploy_turn(now: float) -> None:
    """Each worker turn: a pending deploy pauses measurement for itself and alerts once if it waits too long (#1672); a dead gateway switch is settled (#1899)."""
    from harness import gateway_switch
    try:
        said = preempt_for_deploy(now)
    except Exception as exc:  # noqa: BLE001 - preempting must not stop the worker, on any store
        said = [f"preempting for the deploy failed: {exc}"]
    for line in said:
        print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)
    watch_deploys(now)
    gateway_switch.turn()
