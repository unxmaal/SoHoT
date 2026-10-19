"""Refuse a deploy while a sweep or an eval runs: a running loop keeps the code it imported. #1000.

scripts/launchd.sh runs this as a file before it checks out a new commit, so it imports nothing outside
the stdlib. Exit 0 lets the deploy go ahead; anything else refuses it.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

OVERRIDE = "LH_DEPLOY_DURING_SWEEP"
#: harness/heartbeat.path(), evals/watch.PROGRESS and harness/paths.runs(), restated because this imports nothing.
HEARTBEAT = "loop-heartbeat.json"
PROGRESS = "progress.json"
RUNS = "runs"
LOOP = re.compile(r"(?:serve-discover\.sh|serve-canary\.sh|\bdiscover\b.*--loop|\bsoh\b.*\bcanary\b)")
EVAL = re.compile(r"(?:-m\s+evals\.run\b|evals/run\.py\b)")
STOP_GRACE_S = 30.0
PS_TIMEOUT_S = 10.0
OK, REFUSED = 0, 1


def alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def command_of(pid: int) -> str | None:
    """The process's command line, '' when it is gone, None when this platform cannot say."""
    if sys.platform == "win32":
        return None
    try:
        got = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True,
                             timeout=PS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    return got.stdout.strip() if got.returncode == 0 else ""


def _read(path: Path) -> dict:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _pid(raw) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def running(root: Path, alive=alive, command_of=command_of) -> list[dict]:
    """The live discover loop and evals under `root`, each {what, pid, started, commit, command}."""
    found = []
    beat = _read(root / HEARTBEAT)
    candidates = []
    if beat.get("state") == "running":
        candidates.append(("discover loop", _pid(beat.get("pid")), beat.get("started"), beat.get("commit", ""), LOOP))
    runs = root / RUNS
    for path in sorted(runs.glob(f"*/{PROGRESS}")) if runs.is_dir() else []:
        got = _read(path)
        if got.get("state") == "running":
            candidates.append((f"eval {path.parent.name}", _pid(got.get("pid")), got.get("started_at"), "", EVAL))
    for what, pid, started, commit, pattern in candidates:
        if not alive(pid):
            continue
        command = command_of(pid)
        # A pid the file names but another program now holds is not ours to refuse on or to stop.
        if command is not None and not pattern.search(command):
            continue
        found.append({"what": what, "pid": pid, "started": started, "commit": commit or "",
                      "command": command or ""})
    return found


def _when(at) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(at)))
    except (TypeError, ValueError):
        return "an unknown time"


def describe(r: dict) -> str:
    on = f" on {r['commit'][:12]}" if r.get("commit") else ""
    return f"{r['what']} (pid {r['pid']}, started {_when(r['started'])}{on})"


def _signal(kill, pid: int, sig) -> bool:
    try:
        kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


def stop(found: list[dict], grace: float = STOP_GRACE_S, alive=alive, kill=os.kill, sleep=time.sleep,
         clock=time.monotonic) -> list[int]:
    """TERM each, as the watchdog's stop does, then KILL what outlives `grace`; the pids still alive."""
    for r in found:
        _signal(kill, r["pid"], signal.SIGTERM)
    deadline = clock() + grace
    while clock() < deadline and any(alive(r["pid"]) for r in found):
        sleep(0.2)
    for r in found:
        if alive(r["pid"]):
            _signal(kill, r["pid"], getattr(signal, "SIGKILL", signal.SIGTERM))
    sleep(0.2)
    return [r["pid"] for r in found if alive(r["pid"])]


def settle_heartbeat(root: Path, stopped: list[dict], alive=alive) -> None:
    """A loop stopped before it could finish says so, on the commit it started on, so no reader calls it stalled."""
    path = root / HEARTBEAT
    beat = _read(path)
    pids = {r["pid"] for r in stopped}
    if beat.get("state") != "running" or _pid(beat.get("pid")) not in pids or alive(_pid(beat.get("pid"))):
        return
    now = time.time()
    beat.update(state="finished", rc=None, finished=now, updated=now, finished_commit=beat.get("commit", ""),
                error=f"stopped for a deploy ({OVERRIDE}=1)")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(beat), encoding="utf-8")
    os.replace(tmp, path)


def check(root: Path, environ=None, err=None, alive=alive, command_of=command_of, stopper=stop) -> int:
    environ = os.environ if environ is None else environ
    err = sys.stderr if err is None else err
    found = running(root, alive=alive, command_of=command_of)
    if not found:
        return OK
    names = "; ".join(describe(r) for r in found)
    if environ.get(OVERRIDE) != "1":
        print(f"REFUSING to deploy: {names}. A running loop keeps the code it imported, so a deploy now "
              f"leaves it on the old code until it ends.", file=err)
        print(f"Wait for it to finish, or stop it and deploy: {OVERRIDE}=1 ./scripts/launchd.sh install "
              f"(a measurement it was in resumes next sweep)", file=err)
        return REFUSED
    print(f"WARNING: {OVERRIDE}=1, stopping {names} before the deploy", file=err)
    left = stopper(found)
    settle_heartbeat(root, [r for r in found if r["pid"] not in left], alive=alive)
    if left:
        print(f"REFUSING to deploy: pid(s) {', '.join(map(str, left))} outlived SIGKILL", file=err)
        return REFUSED
    print(f"stopped {len(found)}; the next sweep runs the deployed code", file=err)
    return OK


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0]:
        print("usage: sweep_guard.py LOCALHARNESS_HOME", file=sys.stderr)
        return 2
    return check(Path(argv[0]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
