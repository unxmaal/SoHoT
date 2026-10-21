"""A child's download rate held under a cap by stopping and continuing it: no sudo, any download path. #1084."""
import signal
import sys

import pytest

from harness import throttle

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="SIGSTOP and SIGCONT are POSIX; the cap runs on macOS")


class _World:
    """A child that receives `line` bytes a second while running, until `total`."""

    def __init__(self, line, total, slow_until=0.0, slow=0.0):
        self.t, self.bytes, self.running, self.line, self.total, self.signals = 0.0, 0.0, True, line, total, []
        self.pid, self.slow_until, self.slow, self.ticks, self._last = 1, slow_until, slow, [], 0.0

    def _pass(self, s):
        if self.running:
            rate = self.slow if self.t < self.slow_until else self.line
            self.bytes = min(self.total, self.bytes + rate * s)
        self.t += s

    def sleep(self, s):
        self._pass(s)

    def read(self, w):
        self._pass(w)
        if w:
            self.ticks.append(self.bytes - self._last)
            self._last = self.bytes
        return int(self.bytes)

    def signal_to(self, sig):
        self.signals.append(sig)
        if sig in (signal.SIGSTOP, signal.SIGCONT):
            self.running = sig == signal.SIGCONT

    def poll(self):
        return 0 if self.bytes >= self.total else None

    def wait(self, timeout=None):
        return 0


def test_the_cap_holds_the_average_rate_of_a_fast_line():
    """Measured on the Studio: 43 MB/s uncapped; a 5 MB/s cap gave 4.78 MB/s over a real 86 MB download."""
    w = _World(line=43 * throttle.MB, total=500 * throttle.MB)
    got = throttle.hold(w, 5 * throttle.MB, w.read, clock=lambda: w.t, sleep=w.sleep, signal_to=w.signal_to)
    rate = got["capped_bytes"] / got["capped_s"] / throttle.MB
    assert 4.0 <= rate <= 5.5, got
    # Slices, not whole ticks at line rate: after the first tick no second takes much over the cap.
    assert max(w.ticks[2:]) <= 1.5 * 5 * throttle.MB, max(w.ticks[2:]) / throttle.MB


def test_a_slow_spell_buys_no_burst_over_the_cap():
    w = _World(line=43 * throttle.MB, total=300 * throttle.MB, slow_until=30.0, slow=1 * throttle.MB)
    throttle.hold(w, 5 * throttle.MB, w.read, clock=lambda: w.t, sleep=w.sleep, signal_to=w.signal_to)
    # The rise to line rate costs one tick; 30 s under the cap saved no credit to spend after it.
    windows = [sum(w.ticks[i:i + 10]) for i in range(len(w.ticks) - 9)]
    assert max(windows) <= 1.5 * 10 * 5 * throttle.MB, max(windows) / throttle.MB


def test_outside_the_capped_hours_it_runs_at_line_rate():
    w = _World(line=43 * throttle.MB, total=500 * throttle.MB)
    got = throttle.hold(w, 5 * throttle.MB, w.read, capped=lambda: False, clock=lambda: w.t, sleep=w.sleep,
                        signal_to=w.signal_to)
    assert got["seconds"] < 13 and signal.SIGSTOP not in w.signals


def test_a_stop_continues_the_child_before_ending_it():
    w = _World(line=43 * throttle.MB, total=500 * throttle.MB)
    calls = iter(["", "", "", "the night begins"])
    got = throttle.hold(w, 1 * throttle.MB, w.read, stop=lambda: next(calls), clock=lambda: w.t,
                        sleep=w.sleep, signal_to=w.signal_to)
    assert got["stopped"] == "the night begins"
    assert w.signals[-2:] == [signal.SIGCONT, signal.SIGTERM] and w.running


def test_a_nettop_row_reads_its_own_pid():
    assert throttle.parse("07:53:24.086446,curl.51849,7623843,", 51849) == 7623843
    assert throttle.parse("07:53:24.086446,curl.51849,7623843,", 4242) is None
    assert throttle.parse("time,,bytes_in,", 51849) is None


