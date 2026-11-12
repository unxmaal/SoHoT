"""Who holds a queue pause flag: a dead holder's pause is lifted, an owner's never is. #1760."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from harness import proc_identity

#: The env var a script sets to its own pid, so a pause it takes is lifted once that pid is gone.
HOLDER_ENV = "LH_QUEUE_HOLDER"
_TAG = "holder "
_STAMP = "%Y-%m-%dT%H:%M:%S"


def text(why: str, holder: int | None) -> str:
    """A flag's body: when and why, then the holder's identity when a process holds it."""
    head = f"{time.strftime(_STAMP)} {why}".strip()
    return head if holder is None else f"{head}\n{_TAG}{json.dumps(proc_identity.identity(holder))}"


def holder_of(body: str) -> dict | None:
    """The identity a flag body records, None for an owner's pause."""
    for line in body.splitlines()[1:]:
        if line.startswith(_TAG):
            try:
                got = json.loads(line[len(_TAG):])
            except ValueError:
                return None
            return got if isinstance(got, dict) else None
    return None


def from_env(environ=None) -> int | None:
    got = (environ if environ is not None else os.environ).get(HOLDER_ENV, "")
    return int(got) if got.isdigit() else None


def lift(flags: list[Path]) -> list[str]:
    """Remove each flag whose recorded holder is gone; a holder that cannot be read ('cannot say') keeps it."""
    said = []
    for flag in flags:
        try:
            body = flag.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue
        rec = holder_of(body)
        if rec is None or proc_identity.same(rec) is not False:
            continue
        try:
            if flag.read_text(encoding="utf-8") != body:
                continue  # paused again since it was read
        except FileNotFoundError:
            continue
        flag.unlink(missing_ok=True)
        said.append(f"{flag.name} lifted: its holder pid {rec.get('pid')} is gone ({body.splitlines()[0]})")
    for line in said:
        print(f"{time.strftime('%H:%M:%S')} {line}", file=sys.stderr, flush=True)
    return said


def why_paused(flag: Path) -> str:
    """The gate's reason for a paused queue: an owner's pause, or the process whose end lifts it."""
    try:
        body = flag.read_text(encoding="utf-8")
    except FileNotFoundError:
        body = ""
    rec = holder_of(body)
    if rec is None:
        return "paused (soh jobs resume)"
    return f"held by pid {rec.get('pid')} ({body.splitlines()[0]}); lifted when it ends"


def release(held: Path, flag: Path) -> str:
    """Lift the deploy hold whose marker is held; an owner's pause, or one set since, stays. #1675."""
    if not held.exists():
        return "queue not held for a deploy; left as it was"
    mine = held.read_text(encoding="utf-8")
    held.unlink(missing_ok=True)
    if flag.exists() and flag.read_text(encoding="utf-8") == mine:
        flag.unlink(missing_ok=True)
        return "queue released after the deploy"
    return "queue left as it is: it was paused again during the deploy (soh jobs resume)"
