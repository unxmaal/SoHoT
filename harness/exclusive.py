"""One large working set at a time, across processes. Issue #137.

An in-process queue (the MCP server's, retired in #353) guarded only its own
caller and left `lh` free to collide with itself. Every `lh` invocation is a
new process, so serialising them needs the operating system.

MEASURED, NOT ASSUMED. 2026-09-12 on the M2 Pro: `lh image` started while
`lh video` held the GPU. Both went straight at it, Metal returned
kIOGPUCommandBufferCallbackErrorTimeout, swap reached 8.0 GB of 9.2, and both
jobs were killed with no artifact. That is ERROR #33 and assumption C4.

An advisory file lock, NOT a pidfile. A lock the kernel holds is released when
the process dies however it dies -- killed, crashed, OOM -- so there is no
stale-lock path to get wrong. The 2026-09-12 incident ended in exactly the kill
a pidfile scheme handles worst.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from pathlib import Path

from harness import paths

#: What holds the lock, for a waiter to report. Best-effort and advisory: the
#: LOCK is the truth, this is only how a waiter says what it is waiting behind.
HOLDER = "generation.holder"
LOCK = "generation.lock"

#: Which lanes need the whole machine, declared once rather than tested for at
#: each call site.
#:
#: THE ABSENT ONES ARE THE DELIBERATE PART. svg, web, code and extract go to
#: mlx_lm.server, which already serialises through a single queue of its own;
#: say and hear go to a small resident audio service. Making `lh extract` --
#: one run of one prompt at 0.96s, M2 Pro, 2026-09-12, never repeated -- wait
#: behind a 40-minute video would be a downgrade wearing the clothes of
#: enforcement. The argument does not rest on that number: two orders of
#: magnitude is the claim, and a re-measurement would have to find seconds
#: rather than milliseconds to change it. The resource protected here is a
#: large LOCAL working set, not the machine.
EXCLUSIVE = {"image", "video"}
#: Batch runs that load models on any engine, and other projects through
#: scripts/with-gpu-lock. A lane prompt is not one of these. #314.
BATCH = {"eval", "ramp", "external", "chaos"}
#: Batch kinds that reach their models through the gateway, so they load the serving machine, not this one. #769.
GATEWAY_BATCH = {"eval"}
#: Set while held, so a child that also asks (a helper running `lh ...`)
#: does not deadlock against its own parent.
HELD_ENV = "LH_GPU_LOCK_HELD"

#: How often a waiter re-reads the holder to refresh what it reports.
POLL_SECONDS = 0.5


def _dir() -> Path:
    d = paths.home() / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path() -> Path:
    return _dir() / LOCK


def holder_path() -> Path:
    return _dir() / HOLDER


def holder() -> dict:
    """Who has it, or {}. Never raises: a waiter reporting nothing is fine,
    a waiter crashing because the holder exited mid-read is not."""
    try:
        return json.loads(holder_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def identity(record: dict) -> tuple:
    """WHAT is being waited on, with no clock in it.

    `describe` carries the elapsed seconds because a waiter wants to see them,
    and that made it useless for change detection: the string differs on every
    poll, so a caller comparing descriptions reprinted the same line once a
    second for the length of the wait. Measured 2026-09-12: 89 lines for one
    89-second wait behind an image.
    """
    return (record.get("kind"), record.get("pid"))


def describe(record: dict) -> str:
    kind = record.get("kind") or "something"
    pid = record.get("pid")
    since = record.get("since")
    for_ = f" for {time.time() - since:.0f}s" if isinstance(since, (int, float)) else ""
    return f"{kind}{for_}" + (f" (pid {pid})" if pid else "")


def _take(fd: int) -> bool:
    """Try to take the lock without blocking. True if taken."""
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _release(fd: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


def remote(kind: str, environ=None) -> bool:
    """Whether `kind` loads another machine: a gateway batch whose gateway is not this machine. #769."""
    if kind not in GATEWAY_BATCH:
        return False
    from harness import batch, completion
    return not batch.is_here(completion.gateway_url(environ))


@contextlib.contextmanager
def _named():
    """This process and its children run under one batch id, which every gateway request names. #769."""
    from harness import batch
    if batch.current():
        yield batch.current()
        return
    os.environ[batch.ENV] = batch.new_id()
    try:
        yield os.environ[batch.ENV]
    finally:
        os.environ.pop(batch.ENV, None)


def _claim(mine: str, who: dict) -> dict:
    from harness import batch
    from harness import memory_store as ms
    from harness import workqueue as wq
    conn = ms.connect()
    try:
        return batch.claim(conn, batch.here(), mine, who=who, alive=wq.alive)
    finally:
        conn.close()


def _owner() -> dict:
    from harness import lease
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        return lease.owner(conn)
    finally:
        conn.close()


def _let_go(mine: str) -> None:
    from harness import batch
    from harness import memory_store as ms
    with contextlib.suppress(Exception):
        conn = ms.connect()
        try:
            batch.let_go(conn, batch.here(), mine)
        finally:
            conn.close()


@contextlib.contextmanager
def _renewing(mine: str, who: dict):
    """Keep this machine's batch lease while the block runs, then drop it."""
    import threading

    from harness import batch
    stop = threading.Event()

    def keep():
        while not stop.wait(batch.TTL_S / 3):
            with contextlib.suppress(Exception):
                _claim(mine, who)

    t = threading.Thread(target=keep, name="batch-lease", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=5)
        _let_go(mine)


@contextlib.contextmanager
def _leased(announce, poll: float):
    """Hold this machine's serving lease, the one its gateway gives a remote batch, waiting while another has it. #769."""
    from harness import batch
    with _named() as mine:
        try:
            who = _owner()
        except Exception as exc:  # noqa: BLE001 - the flock still holds this machine
            if announce:
                announce(f"no batch lease (the store would not open: {exc}); holding the local lock only")
            yield False
            return
        waited, said = False, None
        while (got := _claim(mine, who)):
            waited = True
            if announce and got.get("batch") != said:
                announce(f"waiting for {batch.describe(got)} on this machine to finish")
                said = got.get("batch")
            time.sleep(poll)
        with _renewing(mine, who):
            yield waited


@contextlib.contextmanager
def held(kind: str, announce=None, poll: float = POLL_SECONDS, deadline_s: float | None = None):
    """Hold the machine for `kind`, waiting if someone else has it.

    `announce` is called with a sentence the first time this has to wait, and
    again whenever what it is waiting behind changes. Waiting silently for
    forty minutes is indistinguishable from hanging.
    """
    if kind not in EXCLUSIVE | BATCH or os.environ.get(HELD_ENV) == "1":
        yield False
        return
    if remote(kind):
        # The serving gateway holds its machine for this batch; this machine is not loaded. #769.
        with _named():
            yield False
        return

    path = lock_path()
    # Opened for the whole block: on Windows the lock is on the open handle,
    # and closing it anywhere would release it early.
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        waited = False
        said = None
        while not _take(fd):
            waited = True
            record = holder()
            who = identity(record)
            if announce and who != said:
                announce(f"waiting for {describe(record)} to finish")
                said = who
            time.sleep(poll)

        try:
            with _leased(announce, poll) as lease_waited:
                _write_holder(kind, deadline_s)
                os.environ[HELD_ENV] = "1"
                try:
                    yield waited or lease_waited
                finally:
                    os.environ.pop(HELD_ENV, None)
                    with contextlib.suppress(OSError):
                        holder_path().unlink()
        finally:
            _release(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def try_held(kind: str):
    """Hold the machine for `kind` only if it is free now; yields whether it is held."""
    if os.environ.get(HELD_ENV) == "1":
        yield True
        return
    fd = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not _take(fd):
            yield False
            return
        try:
            with _named() as mine:
                try:
                    who = _owner()
                    busy = _claim(mine, who)
                except Exception:  # noqa: BLE001 - the flock still holds this machine
                    who, busy = None, {}
                if busy:
                    yield False
                    return
                with _renewing(mine, who) if who else contextlib.nullcontext():
                    _write_holder(kind)
                    os.environ[HELD_ENV] = "1"
                    try:
                        yield True
                    finally:
                        os.environ.pop(HELD_ENV, None)
                        with contextlib.suppress(OSError):
                            holder_path().unlink()
        finally:
            _release(fd)
    finally:
        os.close(fd)


def _write_holder(kind: str, deadline_s: float | None = None) -> None:
    record = {"kind": kind, "pid": os.getpid(), "since": time.time()}
    if deadline_s:
        record["deadline_s"] = float(deadline_s)
    with contextlib.suppress(OSError):
        holder_path().write_text(json.dumps(record), encoding="utf-8")
