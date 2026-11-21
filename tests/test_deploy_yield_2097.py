"""A sweep that yields to a deploy gets the time it waited back, bounded by the morning cutoff. #2097."""
from __future__ import annotations

import json
import time
import types

from harness import paths, power
from harness.commands import loop as loop_cmd


def _local(day: int, hour: int, minute: int = 0) -> float:
    return time.mktime((2026, 11, day, hour, minute, 0, 0, 0, -1))


def _yield_at(at: float, left: float, deploy_s: float) -> tuple[int, float, float]:
    t = {"now": at}

    def busy():
        return t["now"] < at + deploy_s
    got = loop_cmd._after_deploy(left, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"], busy=busy)
    path = paths.home() / loop_cmd.YIELD_FILE
    rest = json.loads(path.read_text(encoding="utf-8"))["left_s"] if path.exists() else 0.0
    return got, rest, t["now"]


def test_a_deploy_due_2h18m_into_a_sweep_leaves_it_its_full_measuring_budget():
    full = float(power.SWEEP_CEILING_H) * 3600
    start = _local(20, 21)
    spent = 2 * 3600 + 18 * 60
    got, rest, _ = _yield_at(start + spent, full - spent, 51 * 60)
    assert got == loop_cmd.YIELDED
    resumed = loop_cmd._ceiling_s(types.SimpleNamespace(ceiling_h=None), environ={"LH_SWEEP_RESUMED": "1"})
    assert spent + resumed == full, "the 51 min the deploy took came out of the sweep's measuring"


def test_the_ceiling_given_back_stops_at_the_morning_cutoff():
    got, rest, now = _yield_at(_local(21, power.SWEEP_MORNING_H - 2), 3 * 3600.0, 3600.0)
    assert got == loop_cmd.YIELDED
    assert now + rest == _local(21, power.SWEEP_MORNING_H)


def test_a_deploy_that_never_finishes_lets_the_sweep_go_on_after_the_wait_cap_without_yielding_again():
    at = _local(20, 23, 18)
    got, rest, now = _yield_at(at, 3 * 3600.0 + 42 * 60, 1e9)
    assert got == loop_cmd.YIELDED
    assert now - at <= power.SWEEP_YIELD_WAIT_S + loop_cmd.YIELD_POLL_S
    assert rest == 3 * 3600.0 + 42 * 60
    assert not loop_cmd._may_yield(environ={"LH_SWEEP_RESUMED": "1"}), "it would yield to the same stuck deploy again"


def test_a_stuck_deploy_near_the_morning_ends_the_sweep_at_the_morning():
    got, rest, now = _yield_at(_local(21, power.SWEEP_MORNING_H, 0) - 1800, 2 * 3600.0, 1e9)
    assert got == 0 and now == _local(21, power.SWEEP_MORNING_H)


def test_a_daytime_sweep_waits_at_most_the_cap_and_gets_its_whole_ceiling_back():
    at = _local(21, 11)
    got, rest, now = _yield_at(at, 5 * 3600.0, 1e9)
    assert got == loop_cmd.YIELDED and rest == 5 * 3600.0
    assert now - at <= power.SWEEP_YIELD_WAIT_S + loop_cmd.YIELD_POLL_S, "a daytime sweep waited for the next morning"


def test_a_sweep_whose_deploy_finished_still_offers_to_yield():
    _yield_at(_local(20, 23, 18), 3600.0, 600.0)
    assert loop_cmd._may_yield(environ={"LH_SWEEP_RESUMED": "1"})
    assert loop_cmd._may_yield(environ={})
