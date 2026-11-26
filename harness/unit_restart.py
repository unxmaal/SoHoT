"""Restart one launchd unit through scripts/launchd.sh restart, the path the watchdog and gateway switch use; never unload. #2134."""
from __future__ import annotations

import subprocess
import sys

#: Seconds the restart may take: it waits for the machine lock a model-loading run holds.
RESTART_TIMEOUT_S = 300.0


def restart(name: str, run=subprocess.run, platform: str | None = None) -> dict:
    """{rc, line}: `launchd.sh restart NAME` for a unit launchd.sh installs; nothing runs for another name or off macOS."""
    from harness import install_env, paths
    platform = platform or sys.platform
    script = paths.REPO / "scripts" / "launchd.sh"
    if name not in install_env.services(script):
        return {"rc": 2, "line": f"{name!r} is not a unit scripts/launchd.sh installs"}
    if platform != "darwin":
        return {"rc": 2, "line": f"no launchd on {platform}: nothing restarted"}
    try:
        got = run([str(script), "restart", name], capture_output=True, text=True, timeout=RESTART_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"rc": 1, "line": f"launchd.sh restart {name} did not return in {RESTART_TIMEOUT_S:.0f} s"}
    said = ((got.stdout or "") + (got.stderr or "")).strip()[-300:]
    return {"rc": got.returncode, "line": f"restarted {name}" if got.returncode == 0 else f"restart {name} exited {got.returncode}: {said}"}
