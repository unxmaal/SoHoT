"""Is someone using this machine right now? The work queue waits while they are. #353."""
from __future__ import annotations

import os
import re
import subprocess
import sys

#: Minutes without keyboard or mouse input before the owner counts as away.
IDLE_MINUTES_ENV = "LH_IDLE_MINUTES"
DEFAULT_IDLE_MINUTES = 10.0


def _ioreg(args, run) -> str:
    try:
        return run(["ioreg", *args], capture_output=True, text=True,
                   timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def idle_seconds(run=subprocess.run) -> float | None:
    """Seconds since the last keyboard or mouse event, or None if unknown."""
    got = re.search(r'"HIDIdleTime" = (\d+)',
                    _ioreg(["-c", "IOHIDSystem", "-d", "4"], run))
    return int(got.group(1)) / 1e9 if got else None


def locked(run=subprocess.run) -> bool:
    return '"IOConsoleLocked" = Yes' in _ioreg(["-n", "Root", "-d", "1"], run)


def threshold_s(environ=None) -> float:
    environ = os.environ if environ is None else environ
    try:
        return float(environ.get(IDLE_MINUTES_ENV, DEFAULT_IDLE_MINUTES)) * 60
    except ValueError:
        return DEFAULT_IDLE_MINUTES * 60


def away(run=subprocess.run, environ=None, platform=sys.platform) -> tuple[bool, str]:
    """(away, why). Unknown counts as present: a wrong 'away' interrupts someone."""
    if platform != "darwin":
        return True, "no presence probe on this platform"
    if locked(run):
        return True, "screen locked"
    idle = idle_seconds(run)
    if idle is None:
        return False, "idle time unreadable"
    need = threshold_s(environ)
    if idle >= need:
        return True, f"idle {idle / 60:.0f} min"
    return False, f"in use (idle {idle / 60:.1f} of {need / 60:.0f} min)"
