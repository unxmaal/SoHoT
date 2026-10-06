"""Jobs from any caller, run in order under the machine lock while the owner is away. #353."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from harness import exclusive, paths

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"


def root() -> Path:
    d = paths.home() / "queue" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = paths.logs() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(job_id: str) -> Path:
    return root() / f"{job_id}.json"


def _write(job: dict) -> None:
    tmp = _path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=1), encoding="utf-8")
    os.replace(tmp, _path(job["id"]))


def jobs() -> list[dict]:
    out = []
    for f in sorted(root().glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def add(argv: list[str], title: str = "", cwd: str = "", kind: str = "command",
        output: str = "", priority: int = 0) -> dict:
    if not argv:
        raise ValueError("a job needs a command")
    first = str(argv[0])
    if first.startswith("-"):
        raise ValueError(f"the command starts with {first!r}: an option this "
                         f"lh did not recognise was taken as the command")
    if any(c.isspace() for c in first) and not os.path.exists(first):
        raise ValueError(f"{first!r} is a whole command line in one argument; "
                         f"split it into words (zsh does not word-split $VAR). #363")
    taken = [int(j["id"]) for j in jobs() if str(j.get("id", "")).isdigit()]
    job = {"id": f"{max(taken, default=0) + 1:04d}", "title": title or " ".join(argv),
           "kind": kind, "output": output, "priority": int(priority),
           "argv": list(argv), "cwd": cwd or os.getcwd(), "state": PENDING,
           "added": time.strftime("%Y-%m-%dT%H:%M:%S"), "started": "",
           "finished": "", "rc": None, "log": ""}
    _write(job)
    return job


def order(got: list[dict]) -> list[dict]:
    """Run order: higher priority first, then the order added. #361."""
    return sorted(got, key=lambda j: (-int(j.get("priority") or 0), j["id"]))


def pending() -> list[dict]:
    return order([j for j in jobs() if j["state"] == PENDING])


def set_priority(job_id: str, priority: int) -> dict:
    job = get(job_id)
    if job is None:
        raise ValueError(f"no job {job_id}")
    if job["state"] != PENDING:
        raise ValueError(f"job {job_id} is {job['state']}; only a pending job can be reordered")
    job["priority"] = int(priority)
    _write(job)
    return job


def get(job_id: str) -> dict | None:
    return next((j for j in jobs() if j["id"] == job_id), None)


def _pause_flag() -> Path:
    return root().parent / "paused"


def paused() -> bool:
    return _pause_flag().exists()


def pause() -> None:
    _pause_flag().write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def resume() -> None:
    _pause_flag().unlink(missing_ok=True)


def gate(away=None) -> tuple[bool, str]:
    """(open, why): may the next job start now? A running job always finishes."""
    from harness import presence
    if paused():
        return False, "paused (lh jobs resume)"
    gone, why = (away or presence.away)()
    return (True, why) if gone else (False, f"owner present: {why}")


def cancel(job_id: str) -> dict:
    job = next((j for j in jobs() if j["id"] == job_id), None)
    if job is None:
        raise ValueError(f"no job {job_id}")
    if job["state"] != PENDING:
        raise ValueError(f"job {job_id} is {job['state']}; only a pending job can be cancelled")
    _path(job_id).unlink()
    return job


def _runner_lock():
    """An fd holding the one-runner lock, or None if a runner already has it."""
    root()
    fd = os.open(paths.home() / "queue" / "runner.lock", os.O_RDWR | os.O_CREAT, 0o644)
    if exclusive._take(fd):
        return fd
    os.close(fd)
    return None


def running() -> bool:
    fd = _runner_lock()
    if fd is None:
        return True
    exclusive._release(fd)
    os.close(fd)
    return False


def run_one(job: dict, popen=subprocess.run) -> dict:
    log = log_dir() / f"{job['id']}.log"
    job.update(state=RUNNING, started=time.strftime("%Y-%m-%dT%H:%M:%S"), log=str(log))
    _write(job)
    # No machine lock here: each command takes it for the part that loads a
    # model, so a job that is downloading does not block a GPU run. #371.
    with open(log, "w", encoding="utf-8") as out:
        try:
            rc = popen(job["argv"], cwd=job["cwd"], stdout=out,
                       stderr=subprocess.STDOUT).returncode
        except OSError as exc:
            out.write(f"could not start: {exc}\n")
            rc = 127
    job.update(state=DONE if rc == 0 else FAILED, rc=rc,
               finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
    _write(job)
    return job


def _recover() -> None:
    """Only the runner-lock holder calls this, so nothing is really running:
    a job still marked running was cut off (a reboot) and may be half done."""
    for j in jobs():
        if j["state"] == RUNNING:
            j.update(state=FAILED, note="interrupted; add it again to retry")
            _write(j)


def run_pending(popen=subprocess.run, gate=lambda: (True, "")) -> list[dict]:
    """Work the queue in order while the gate stays open. One runner at a time."""
    fd = _runner_lock()
    if fd is None:
        return []
    done = []
    try:
        _recover()
        while True:
            nxt = next(iter(pending()), None)
            if nxt is None or not gate()[0]:
                return done
            done.append(run_one(nxt, popen=popen))
    finally:
        exclusive._release(fd)
        os.close(fd)


def serve(poll: float = 30.0, sleep=time.sleep, popen=subprocess.run,
          gate_fn=None, forever=True) -> None:
    """The worker service: check the gate every `poll` seconds, run what waits."""
    gate_fn = gate_fn or gate
    said = ""
    while True:
        pending = any(j["state"] == PENDING for j in jobs())
        if pending:
            ok, why = gate_fn()
            if why != said:
                print(f"{time.strftime('%H:%M:%S')} {'running' if ok else 'waiting'}: {why}",
                      flush=True)
                said = why
            if ok:
                ran = run_pending(popen=popen, gate=gate_fn)
                for j in ran:
                    print(f"{time.strftime('%H:%M:%S')} {j['id']} {j['state']} "
                          f"rc={j['rc']} {j['title']}", flush=True)
                if ran:
                    continue
        if not forever:
            return
        sleep(poll)


if __name__ == "__main__":
    serve(poll=float(os.environ.get("LH_QUEUE_POLL", "30")))
