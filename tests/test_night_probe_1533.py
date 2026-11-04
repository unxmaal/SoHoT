"""A lane whose last down would pass lane_probe_unprobed by day gets its deliberate probe the night before. #1533."""
from __future__ import annotations

import time
from datetime import datetime

from harness import lane_probe as lp
from harness import memory_store as ms
from harness import watchdog

ROW = {"lane": "decide", "spec": "s", "base": "b", "upstream": "u", "model": "m", "engine": "e", "reason": "",
       "http_status": None, "error": "", "seconds": None, "prompt_tokens": None, "completion_tokens": None}


def _at(*args) -> float:
    return datetime(2026, 11, *args).timestamp()


def _down(at: float):
    conn = ms.connect()
    lp.record(conn, {**ROW, "outcome": "down"}, at, None)
    return conn


def test_a_daytime_down_is_probed_the_first_night_not_the_night_after():
    conn = _down(_at(3, 12, 25))
    assert lp.due(conn, "decide", None, _at(3, 20, 55), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(3, 21, 5), day=watchdog.daytime).startswith(lp.DELIBERATE)
    assert lp.due(conn, "decide", None, _at(4, 3, 30), day=watchdog.daytime).startswith(lp.DELIBERATE)
    assert lp.due(conn, "decide", None, _at(4, 12, 30), day=watchdog.daytime) == ""


def test_a_night_down_waits_a_day_before_its_probe():
    conn = _down(_at(3, 22, 0))
    assert lp.due(conn, "decide", None, _at(3, 23, 0), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(4, 5, 0), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(4, 21, 5), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(4, 22, 5), day=watchdog.daytime).startswith(lp.DELIBERATE)


def test_a_deliberate_attempt_holds_off_the_next_until_the_following_night():
    conn = _down(_at(3, 12, 25))
    lp.record(conn, {**ROW, "outcome": "slow", "reason": f"{lp.DELIBERATE}: x; no answer"}, _at(4, 3, 30), None)
    assert lp.due(conn, "decide", None, _at(4, 4, 0), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(4, 21, 5), day=watchdog.daytime) == ""
    assert lp.due(conn, "decide", None, _at(5, 3, 35), day=watchdog.daytime).startswith(lp.DELIBERATE)
    assert time.localtime(_at(5, 3, 35)).tm_hour == 3
