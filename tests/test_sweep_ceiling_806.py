"""The discover loop's wall-clock ceiling: each measurement's slice ends at it and pauses. #806, #813."""
import argparse
import time

import pytest

from harness import adopt, ceiling, cli, completion, holdout, power
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd

INC, CH = "llamacpp:Inc", "llamacpp:Ch"


def _ns(**kw):
    base = {"repeat": 1, "effect": 0.4, "power_budget_min": power.BUDGET_MIN}
    return argparse.Namespace(**{**base, **kw})


def _sweep(left_s: float, ceiling_s: float = 6 * 3600.0) -> ceiling.Sweep:
    now = time.time()
    return ceiling.Sweep(ceiling_s, clock=lambda: now, started=now - (ceiling_s - left_s))


def _incumbent(store_run, seconds=10.0):
    split = holdout.for_lane("code")
    rows = [{"case_id": f"{c}#1", "candidate": who, "passed": True, "seconds": seconds,
             "peak_kb": 0, "detail": ""} for c in (*split.dev, *split.holdout) for who in (INC, CH)]
    store_run("inc-1", "code", rows=rows, specs={INC: INC, CH: CH},
              receipt={"max_tokens": completion.budget("code")})


def test_a_measurement_past_the_ceiling_gets_the_rest_of_it_as_its_slice(store_run):
    _incumbent(store_run)
    sweep = _sweep(60.0)
    _, plan = measure_cmd._plan(_ns(), "code", INC, CH, sweep=sweep)
    assert plan.projected_s > 60.0
    assert plan.budget_s == pytest.approx(sweep.remaining())
    assert plan.deadline_s < plan.projected_s


def test_without_a_sweep_the_slice_is_the_measurement_budget(store_run):
    _incumbent(store_run)
    _, plan = measure_cmd._plan(_ns(), "code", INC, CH)
    assert plan.budget_s == power.BUDGET_MIN * 60


def test_a_slice_never_runs_past_the_ceiling_by_more_than_its_grace(store_run):
    _incumbent(store_run)
    sweep = _sweep(3 * 3600.0)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1_000_000), "code", INC, CH, sweep=sweep)
    one = plan.projected_s / (plan.cases_run * plan.repeat)
    assert plan.deadline_s == pytest.approx(sweep.remaining() * power.DEADLINE_GRACE + one)


def test_the_loop_summary_reports_the_ceiling_and_what_it_refused(monkeypatch, capsys):
    from harness import router
    monkeypatch.setattr(router, "settle", lambda why, **k: None)

    def spend(a, rc, failed=None, sweep=None):
        sweep.lines.append("org/c: not run: would end after the sweep ceiling")
        return rc
    monkeypatch.setattr(loop_cmd, "_loop_spend", spend)
    cli._spend_and_settle(argparse.Namespace(), 0, [], _sweep(3600.0))
    out = capsys.readouterr().out
    assert "=== sweep ceiling ===" in out
    assert "6h 00m from" in out and "1h 00m left" in out
    assert "org/c: not run: would end after the sweep ceiling" in out


def test_nothing_is_started_once_the_ceiling_is_reached(monkeypatch):
    launched = []
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: launched.append(argv))
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    assert measure_cmd._measure(_ns(), {"name": CH, "lane": "code"}, [], _sweep(0.0)) == 0
    assert launched == []


def test_the_ceiling_is_a_discover_flag_defaulting_to_the_knob():
    a = cli.build_parser().parse_args(["discover", "--loop"])
    assert a.ceiling_h == power.SWEEP_CEILING_H == 6.0
    assert cli.build_parser().parse_args(["discover", "--ceiling-h", "2"]).ceiling_h == 2.0
