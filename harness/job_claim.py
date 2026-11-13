"""Which worker claimed a queued job, so a job with no pid yet reads as starting, not gone. #1895."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from harness.atomic_file import replace


def path(job_id) -> Path:
    """Beside the job's pid file: the identity of the worker that claimed it, until its process has exited."""
    from harness import workqueue as wq
    return wq._pids() / f"{wq.label(job_id)}.claim"


def mark(job_id, pid: int | None = None) -> None:
    from harness import proc_identity
    to = path(job_id)
    tmp = to.with_suffix(f".claim.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(proc_identity.identity(pid or os.getpid())), encoding="utf-8")
    replace(tmp, to)


def clear(job_id) -> None:
    path(job_id).unlink(missing_ok=True)


def starting(job_id) -> bool:
    """Whether the worker that claimed a job still runs; same() None cannot say it is gone, and an unread mark is not gone either."""
    from harness import proc_identity
    from harness import workqueue as wq
    try:
        rec = json.loads(path(job_id).read_text(encoding="utf-8"))
        pid = int(rec["pid"])
    except FileNotFoundError:
        return False
    except (OSError, ValueError, KeyError, TypeError):
        return True
    return wq.alive(pid) and proc_identity.same(rec) is not False


def await_pid(job_id, wait: float, poll: float = 0.1) -> int | None:
    """The job's pid, waiting up to `wait` s while its worker is still starting it; None when it has none."""
    from harness import workqueue as wq
    end = time.monotonic() + wait
    while True:
        pid = wq._pid_of(job_id)
        if pid is not None or not starting(job_id) or time.monotonic() >= end:
            return pid
        time.sleep(poll)
