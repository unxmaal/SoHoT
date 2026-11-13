"""Reap a signalled child up to a bound: past it the pid and its state are named and the caller goes on (#1925)."""
from __future__ import annotations

import subprocess
import sys

REAP_TIMEOUT_S = 10.0


def state(pid: int) -> str:
    """ps's STAT for pid (D is stuck in the kernel, T stopped), or why it cannot be read."""
    if sys.platform == "win32":
        return "state unread: no ps"
    try:
        got = subprocess.run(["ps", "-o", "stat=", "-p", str(int(pid))], capture_output=True, text=True,
                             encoding="utf-8", timeout=REAP_TIMEOUT_S).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return f"state unread: {type(exc).__name__}"
    return f"state {got}" if got else "no longer listed by ps"


def wait(proc, what: str, timeout: float | None = None) -> bool:
    """True once proc exits within REAP_TIMEOUT_S; else one stderr line naming its pid and state, a cut, False."""
    from harness import cuts
    limit = REAP_TIMEOUT_S if timeout is None else float(timeout)
    try:
        with cuts.timeout("reap_after_kill", f"{what}: pid {proc.pid} not reaped", value=limit):
            proc.wait(timeout=limit)
        return True
    except subprocess.TimeoutExpired:
        print(f"{what}: pid {proc.pid} did not exit within {limit:g} s of its signal ({state(proc.pid)}); "
              f"left running, reap_after_kill", file=sys.stderr, flush=True)
        return False
