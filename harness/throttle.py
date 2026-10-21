"""Hold a child process's download rate under a cap by stopping and continuing it: no sudo, any download path. #1084."""
from __future__ import annotations

import os
import select
import shutil
import signal
import subprocess
import sys
import time

MB = 1_000_000


class Received:
    """A process's cumulative received bytes, from streaming nettop through a pty (a pipe buffers it)."""

    def __init__(self, pid: int):
        if sys.platform == "win32":
            raise OSError("nettop and pty are macOS and POSIX")
        import pty
        self.pid, self.bytes, self._buf = int(pid), 0, b""
        master, slave = pty.openpty()
        self._fd = master
        self._proc = subprocess.Popen(["nettop", "-P", "-x", "-J", "bytes_in", "-p", str(self.pid), "-L", "0", "-s", "1"],
                                      stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.DEVNULL)
        os.close(slave)

    def poll(self, wait: float) -> int:
        """The newest cumulative count, after waiting up to `wait` seconds for a sample."""
        ready, _, _ = select.select([self._fd], [], [], wait)
        if ready:
            try:
                self._buf += os.read(self._fd, 65536)
            except OSError:
                return self.bytes
            *lines, self._buf = self._buf.split(b"\n")
            for line in lines:
                got = parse(line.decode("utf-8", "replace"), self.pid)
                if got is not None:
                    self.bytes = max(self.bytes, got)
        return self.bytes

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        os.close(self._fd)


def parse(line: str, pid: int) -> int | None:
    """bytes_in from one nettop CSV row for `pid` ('time,name.pid,bytes_in,'), else None."""
    parts = [p.strip() for p in line.split(",")]
    for i, part in enumerate(parts[:-1]):
        if part.rpartition(".")[2] == str(pid) and parts[i + 1].isdigit():
            return int(parts[i + 1])
    return None


def available() -> bool:
    """This platform has a per-process byte counter a user may read: nettop on macOS."""
    return sys.platform == "darwin" and bool(shutil.which("nettop"))


def counter(pid: int):
    """A byte counter for `pid`, or None where this platform has none a user may read."""
    return Received(pid) if available() else None


def hold(proc, cap_bps: float, read, *, capped=lambda: True, stop=lambda: "", clock=time.monotonic,
         sleep=time.sleep, tick: float = 1.0, signal_to=None) -> dict:
    """Run `proc` to its end; while capped(), let it run only the slice of each tick its byte allowance buys."""
    send = signal_to or (lambda sig: os.kill(proc.pid, sig))
    start = last = clock()
    got = base = read(0)
    allowed, running, full = float(got), True, True
    capped_s = stopped_s = 0.0
    capped_bytes, why, on, rate, sliced_b, sliced_s = 0, "", 0.0, 0.0, 0, 0.0

    def go(want: bool):
        nonlocal running
        if sys.platform == "win32":
            raise OSError("SIGSTOP and SIGCONT are POSIX")
        if want != running:
            send(signal.SIGCONT if want else signal.SIGSTOP)
            running = want

    while proc.poll() is None:
        why = stop()
        if why:
            go(True)
            send(signal.SIGTERM)
            proc.wait()
            break
        before = got
        got = read(tick if full else max(0.0, tick - on))
        now = clock()
        dt, last = now - last, now
        if not capped():
            go(True)
            allowed, on, full = float(got), 0.0, True
            continue
        capped_s += dt
        capped_bytes += got - before
        if got > before and full and dt > 0:
            # A whole tick's rate is believed at once and starts a new average over the slices after it.
            rate, sliced_b, sliced_s = (got - before) / dt, 0, 0.0
        elif got > before and on > 0:
            # One sample lags its slice, so slices are averaged together, never read one by one.
            sliced_b, sliced_s = sliced_b + got - before, sliced_s + on
            rate = sliced_b / sliced_s
        # Two ticks of credit at most: what a slice missed is spent next tick, and a slow spell buys no burst.
        allowed = min(allowed + cap_bps * dt, got + 2 * cap_bps * tick)
        room = allowed - got
        # Until it has received anything (imports, a listing) it runs whole ticks.
        on = tick if not rate else 0.0 if room <= 0 else min(tick, room / rate)
        full = on >= tick
        stopped_s += max(0.0, dt - on)
        if on <= 0:
            go(False)
            continue
        go(True)
        if not full:
            sleep(on)
            go(False)
    return {"bytes": got - base, "seconds": clock() - start, "capped_s": capped_s, "capped_bytes": capped_bytes,
            "stopped_s": max(0.0, stopped_s), "stopped": why, "line_mb_s": rate / MB if rate else None,
            "capped_rate_mb_s": capped_bytes / capped_s / MB if capped_s else None}
