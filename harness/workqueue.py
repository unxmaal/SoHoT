"""Jobs that wait for a go, then run one at a time under the machine lock. #353."""
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


def add(argv: list[str], title: str = "", cwd: str = "") -> dict:
    if not argv:
        raise ValueError("a job needs a command")
    taken = [int(j["id"]) for j in jobs() if str(j.get("id", "")).isdigit()]
    job = {"id": f"{max(taken, default=0) + 1:04d}", "title": title or " ".join(argv),
           "argv": list(argv), "cwd": cwd or os.getcwd(), "state": PENDING,
           "added": time.strftime("%Y-%m-%dT%H:%M:%S"), "started": "",
           "finished": "", "rc": None, "log": ""}
    _write(job)
    return job


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
    with exclusive.held("external"), open(log, "w", encoding="utf-8") as out:
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


def run_pending(popen=subprocess.run) -> list[dict]:
    """Work the queue in order until nothing is pending. One runner at a time."""
    fd = _runner_lock()
    if fd is None:
        return []
    done = []
    try:
        # Holding the runner lock means nothing else is running: a job still
        # marked running was cut off (a reboot) and may be half done.
        for j in jobs():
            if j["state"] == RUNNING:
                j.update(state=FAILED, note="interrupted; add it again to retry")
                _write(j)
        while True:
            nxt = next((j for j in jobs() if j["state"] == PENDING), None)
            if nxt is None:
                return done
            done.append(run_one(nxt, popen=popen))
    finally:
        exclusive._release(fd)
        os.close(fd)


def go(spawn=subprocess.Popen) -> bool:
    """Start a detached runner. False if one is already running."""
    if running():
        return False
    kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
           | subprocess.DETACHED_PROCESS} if sys.platform == "win32"
          else {"start_new_session": True})
    with open(log_dir() / "runner.log", "a", encoding="utf-8") as out:
        spawn([sys.executable, "-m", "harness.workqueue"], stdout=out,
              stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
              cwd=str(Path(__file__).resolve().parents[1]), **kw)
    return True


if __name__ == "__main__":
    for j in run_pending():
        print(f"{j['id']} {j['state']} rc={j['rc']} {j['title']}", flush=True)
