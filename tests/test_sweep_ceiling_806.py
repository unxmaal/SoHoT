"""The discover loop's wall-clock ceiling, and the lead budget an underpowered challenger-leaning pairing may spend. #806."""
import argparse
import time

import pytest

from harness import adopt, ceiling, cli, completion, holdout, power, reasons
from harness import memory_store as ms
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


def _pair(store_run, gained: int, lost: int, failure_class=reasons.UNDERPOWERED):
    """A paired run on the code holdout, and the adopt verdict read from it."""
    split = holdout.for_lane("code")
    rows = []
    for i, c in enumerate(split.holdout):
        inc_ok, ch_ok = ((False, True) if i < gained else (True, False) if i < gained + lost
                         else (True, True))
        rows += [{"case_id": f"{c}#1", "candidate": INC, "passed": inc_ok, "seconds": 10.0,
                  "peak_kb": 0, "detail": ""},
                 {"case_id": f"{c}#1", "candidate": CH, "passed": ch_ok, "seconds": 10.0,
                  "peak_kb": 0, "detail": ""}]
    rid = store_run("pair-1", "code", rows=rows, specs={INC: INC, CH: CH},
                    receipt={"max_tokens": completion.budget("code")})
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("code", INC, CH, False, "underpowered: power 0.69",
                                         failure_class=failure_class,
                                         evidence={"split": split.as_dict()}),
                     spec=CH, run_id=rid)
    finally:
        conn.close()


def test_a_measurement_that_would_end_past_the_ceiling_is_not_run(store_run):
    _incumbent(store_run)
    _, plan = measure_cmd._plan(_ns(), "code", INC, CH, sweep=_sweep(60.0))
    assert plan.projected_s > 60.0
    assert plan.refused.startswith("not run: would end after the sweep ceiling")


def test_without_a_sweep_the_same_plan_runs(store_run):
    _incumbent(store_run)
    _, plan = measure_cmd._plan(_ns(), "code", INC, CH)
    assert not plan.refused


def test_a_launched_run_is_stopped_at_the_ceiling(store_run):
    _incumbent(store_run)
    sweep = _sweep(3 * 3600.0)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1_000_000), "code", INC, CH, sweep=sweep)
    assert not plan.refused
    assert plan.projected_s <= sweep.remaining()
    assert plan.deadline_s <= sweep.remaining()


def test_a_lead_may_spend_the_rest_of_the_ceiling(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    sweep = _sweep(5 * 3600.0)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=sweep)
    assert not plan.refused
    assert plan.budget_s == pytest.approx(sweep.remaining())
    assert plan.lead.startswith("lead: 10 gained vs 3 lost, p=0.09 on ")
    assert time.strftime("%Y-%m-%d") in plan.lead
    assert plan.lead in plan.why


def test_a_lead_is_extended_once_per_sweep(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    sweep = _sweep(5 * 3600.0)
    measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=sweep)
    _, again = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=sweep)
    assert not again.lead
    assert again.refused.endswith("over the 1m budget")
    _, fresh = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=_sweep(5 * 3600.0))
    assert fresh.lead


def test_a_lead_that_cannot_fit_is_reported_unaffordable(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=_sweep(600.0))
    assert plan.refused.startswith("lead, unaffordable in one sweep:")
    assert "10 gained vs 3 lost" in plan.refused


@pytest.mark.parametrize("gained, lost, cls", [
    (6, 3, reasons.UNDERPOWERED),      # leans to the challenger, p well over 0.10
    (3, 10, reasons.UNDERPOWERED),     # leans to the incumbent
    (10, 3, reasons.INCONCLUSIVE),     # stopped at its deadline: not an underpowered verdict
])
def test_only_an_underpowered_challenger_leaning_verdict_is_a_lead(store_run, gained, lost, cls):
    _incumbent(store_run)
    _pair(store_run, gained=gained, lost=lost, failure_class=cls)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=_sweep(5 * 3600.0))
    assert not plan.lead
    assert plan.refused.endswith("over the 1m budget")


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/ceiling.py:lead")
def test_a_refused_follow_up_does_not_end_the_lead(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=_sweep(600.0))
    measure_cmd._refused(CH, "code", INC, CH, holdout.for_lane("code"), plan)
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "code", INC, CH, sweep=_sweep(5 * 3600.0))
    assert plan.lead.startswith("lead: 10 gained vs 3 lost")


def test_a_later_decided_verdict_does_end_the_lead(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("code", INC, CH, False, "does not beat the incumbent"),
                     spec=CH)
        assert ceiling.lead(conn, "code", INC, CH) is None
    finally:
        conn.close()


def test_a_lead_against_another_incumbent_is_not_this_pairing(store_run):
    _incumbent(store_run)
    _pair(store_run, gained=10, lost=3)
    conn = ms.connect()
    try:
        assert ceiling.lead(conn, "code", "llamacpp:Other", CH) is None
        assert ceiling.lead(conn, "code", INC, CH) is not None
    finally:
        conn.close()


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


def test_the_measure_step_records_a_refusal_in_the_sweep(monkeypatch):
    sweep = _sweep(60.0)
    plan = power.Plan(1, 0.5, 1, 1, 0.1, 0.05, 0.8, 1, False, True, 0, "",
                      refused="not run: would end after the sweep ceiling: x")
    monkeypatch.setattr(measure_cmd, "_plan", lambda *a, **k: (None, plan))
    monkeypatch.setattr(measure_cmd, "_refused", lambda *a: 0)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    measure_cmd._measure(_ns(), {"name": CH, "lane": "code"}, [], sweep)
    assert sweep.lines == [f"{CH}: not run: would end after the sweep ceiling: x"]


def test_the_ceiling_is_a_discover_flag_defaulting_to_the_knob():
    a = cli.build_parser().parse_args(["discover", "--loop"])
    assert a.ceiling_h == power.SWEEP_CEILING_H == 6.0
    assert cli.build_parser().parse_args(["discover", "--ceiling-h", "2"]).ceiling_h == 2.0
