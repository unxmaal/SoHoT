"""Pause the queue and wait, up to a deadline, for the running job to end before a reload or a volume stop. #577, #1762."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from harness import queue_hold, workqueue as wq

#: How long a quiesce waits, the queue paused, for the running job to end. #1762.
QUIESCE_TIMEOUT_S = 1800.0
#: A quiesce's end state when the job outlived QUIESCE_TIMEOUT_S, its stdout line and its exit code. #1762.
NOT_QUIESCED, NOT_QUIESCED_RC = "not-quiesced", 3


class NotQuiesced(RuntimeError):
    """A job outlived the quiesce's deadline; the queue was left as it was found and the owner alerted. #1762."""


def _read(flag: Path) -> str | None:
    try:
        return flag.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _running_names() -> str:
    try:
        got = wq.running_here()
    except (RuntimeError, OSError, ValueError) as exc:
        return f"the running job (the store cannot say which: {type(exc).__name__})"
    return ", ".join(f"job {wq.label(j['id'])} ({j.get('title') or j.get('kind') or ''})" for j in got) or "the running job"


def _expired(limit: float, mine: str | None) -> NotQuiesced:
    """Lift the pause this quiesce took (not one set since), record the cut, alert once, name the end state."""
    from harness import cuts, monitor
    if mine is not None and _read(wq._pause_flag()) == mine:
        wq.resume()
    msg = (f"{NOT_QUIESCED}: {_running_names()} still running after {limit:.0f} s (queue_quiesce_timeout); nothing "
           f"was reloaded or stopped under it and the queue is left as it was found. Re-run `scripts/launchd.sh "
           f"install` (or the volume stop) once it ends, or end it now with `soh jobs cancel ID`")
    cuts.cut("queue_quiesce_timeout", "worker quiesce", value=limit, kept=0, dropped=1)
    try:
        monitor.alert("service", {"MONIT_SERVICE": "queue", "MONIT_EVENT": NOT_QUIESCED, "MONIT_DESCRIPTION": msg})
    except (OSError, ValueError) as exc:
        print(f"{NOT_QUIESCED}: the alert was not sent: {exc}", file=sys.stderr, flush=True)
    return NotQuiesced(msg)


def quiesce(wait=0.5, sleep=time.sleep, is_running=None, holder: int | None = None, timeout: float | None = None,
            clock=time.monotonic) -> bool:
    """Pause the queue and wait until no job runs; the prior paused state, or NotQuiesced past the deadline."""
    was_paused = wq.paused()
    mine = None
    if not was_paused:
        wq.pause(holder=holder)  # an owner's pause is never turned into a holder's. #1760
        mine = _read(wq._pause_flag())
    is_running = is_running or wq.running
    limit = QUIESCE_TIMEOUT_S if timeout is None else timeout
    end, said = clock() + limit, False
    while is_running():
        left = end - clock()
        if left <= 0:
            raise _expired(limit, mine)
        if not said:
            print(f"waiting up to {limit:.0f} s (queue_quiesce_timeout) for {_running_names()} to end",
                  file=sys.stderr, flush=True)
            said = True
        sleep(min(wait, left))
    return was_paused


def cli() -> int:
    """`python -m harness.workqueue quiesce`: was-paused, was-running, or not-quiesced with rc NOT_QUIESCED_RC."""
    try:
        print("was-paused" if quiesce(holder=queue_hold.from_env()) else "was-running", flush=True)
    except NotQuiesced as exc:
        print(NOT_QUIESCED, flush=True)
        print(exc, file=sys.stderr, flush=True)
        return NOT_QUIESCED_RC
    return 0
