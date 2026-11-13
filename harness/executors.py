"""How a queued job runs: an executor starts its command, and stops it on cancel. Only the host's for now; containers later (#1510). #1508."""
from __future__ import annotations

import subprocess
from typing import Protocol

HOST = "host"


class Executor(Protocol):
    name: str

    def run(self, job: dict, argv, cwd=None, stdout=None, env=None) -> subprocess.Popen:
        """Run the job's command to its end, its output into stdout; the finished process."""

    def stop(self, pid: int, grace: float | None = None) -> str:
        """Stop the job's processes, waiting up to grace before a kill: "term", "kill" or "gone"."""


class Host:
    """A native process group on this machine, its pid where cancel finds it: GPU work runs here. #628."""

    name = HOST

    def run(self, job: dict, argv, cwd=None, stdout=None, env=None) -> subprocess.Popen:
        from harness import proc_identity
        from harness import workqueue as wq
        pid_file = wq._pid_file(job["id"])
        exit_file(pid_file).unlink(missing_ok=True)
        child = wq.spawn_group(gated(argv, pid_file), cwd, stdout, env)
        try:
            started_file(pid_file).write_text(f"{child.pid} {proc_identity.started(child.pid)}", encoding="utf-8")
            pid_file.write_text(str(child.pid), encoding="utf-8")
        except BaseException:
            # The gate would wait on a live worker for a pid that is never written.
            child.kill()
            child.wait()
            raise
        try:
            rc = child.wait()
            # Before the pid file goes, so a worker that dies before settling leaves the exit to settle by. #1758.
            _write(exit_file(pid_file), str(rc))
            left = self.stop(child.pid)
            if left != "gone" and stdout is not None:
                stdout.write(f"stopped processes the job left running: {left}\n")
        finally:
            pid_file.unlink(missing_ok=True)
            started_file(pid_file).unlink(missing_ok=True)
        return child

    def stop(self, pid: int, grace: float | None = None) -> str:
        from harness import workqueue as wq
        return wq.stop_group(pid) if grace is None else wq.stop_group(pid, grace=grace)


#: The job's command waits for its own pid in the pid file, so a worker that dies before writing it leaves no job running. #1758.
GATE = """import os, sys, time
pid_file, parent, argv = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
me = str(os.getpid())
while True:
    try:
        with open(pid_file, encoding="utf-8") as f:
            if f.read().strip() == me:
                break
    except OSError:
        pass
    if os.getppid() != parent:
        sys.exit("not started: its worker died before recording its pid")
    time.sleep(0.01)
try:
    os.execvp(argv[0], argv)
except OSError as exc:
    print(f"could not start: {exc}", flush=True)
    sys.exit(127)
"""


def gated(argv, pid_file) -> list[str]:
    """argv behind GATE where exec keeps the pid; Windows has no exec, so its job starts at once."""
    import os
    import sys
    if sys.platform == "win32":
        return list(argv)
    return [sys.executable, "-I", "-c", GATE, str(pid_file), str(os.getpid()), *map(str, argv)]


def exit_file(pid_file):
    """Beside a job's pid file, its command's exit code, written before the pid file is removed. #1758."""
    return pid_file.with_suffix(".exit")


def exit_record(pid_file) -> int | None:
    try:
        return int(exit_file(pid_file).read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return None


def _write(path, text: str) -> None:
    import os
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def started_file(pid_file):
    """Beside a job's pid file, "<pid> <start time>": the pid file stays a bare integer that older releases read. #1820."""
    return pid_file.with_suffix(".started")


def pid_record(path) -> tuple[int, str]:
    """(pid, start time or '') for a job's pid file; '' when no start time was recorded for that pid. #1820."""
    pid = int(path.read_text(encoding="utf-8").strip())
    try:
        got = started_file(path).read_text(encoding="utf-8").split()
    except OSError:
        return pid, ""
    return pid, got[1] if len(got) == 2 and got[0] == str(pid) else ""


EXECUTORS: dict[str, Executor] = {HOST: Host()}


def for_job(job: dict) -> Executor:
    """The executor a job runs under: the host's, the only one until containers can hand GPU work to it."""
    return EXECUTORS[HOST]
