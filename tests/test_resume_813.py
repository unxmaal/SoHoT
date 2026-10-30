"""The measure step pauses at its slice, looks, resumes first next sweep, and restarts a changed exam. #813."""
import argparse
import json
import time
from pathlib import Path

import pytest

from evals import watch
from harness import adopt, ceiling, holdout, looks, paused, power
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.commands.measure import Launched

INC, CH = "llamacpp:Inc", "llamacpp:Ch"


def _ns(**kw):
    return argparse.Namespace(**{"repeat": 1, "effect": 0.4, "power_budget_min": 60.0, **kw})


def _sweep(left_s: float = 3 * 3600.0) -> ceiling.Sweep:
    now = time.time()
    return ceiling.Sweep(6 * 3600.0, clock=lambda: now, started=now - (6 * 3600.0 - left_s))


def _rows(n: int, gained: int = 0, lost: int = 0) -> list[dict]:
    """Paired rows over the first n holdout cases: `gained` cells only the challenger passes, `lost` only the incumbent."""
    out = []
    for i, c in enumerate(holdout.for_lane("code").holdout[:n]):
        inc_ok, ch_ok = ((False, True) if i < gained else (True, False) if i < gained + lost
                         else (True, True))
        out += [{"case_id": c, "candidate": INC, "passed": inc_ok, "seconds": 1.0, "wall_s": 1.0},
                {"case_id": c, "candidate": CH, "passed": ch_ok, "seconds": 1.0, "wall_s": 1.0}]
    return out


class Eval:
    """Stands in for evals.run: writes a checkpoint and progress for the rows it is given, then exits `rc`."""

    def __init__(self, rc=watch.PAUSED, rows=None, timed_out=False):
        self.rc, self.rows, self.timed_out, self.argvs = rc, rows or [], timed_out, []

    def __call__(self, argv, **kw):
        self.argvs.append(argv)
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        if "--resume" not in argv or not (out / watch.CHECKPOINT).exists():
            watch.Checkpoint(out, {"x": 1})
        ck = watch.Checkpoint(out, {"x": 1}, keep=True)
        have = len((watch.read(out) or ({}, []))[1])
        for r in self.rows[have:]:
            ck.add(r, r["wall_s"])
        total = 2 * len(holdout.for_lane("code").holdout)
        (out / watch.PROGRESS).write_text(json.dumps({
            "state": "paused", "done": len(self.rows), "total": total, "specs": {INC: INC, CH: CH},
            "planned_s_per_case": {INC: 1.0, CH: 2.0}, "observed_s_per_case": {INC: 1.5, CH: 2.5},
            "run_id": None}), encoding="utf-8")
        return Launched(None if self.timed_out else self.rc, "", self.timed_out, 1.0)


@pytest.fixture
def world(monkeypatch, tmp_path):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    return lambda: real(tmp_path / "d.db")


def _measure(sweep=None):
    return measure_cmd._measure(_ns(), {"name": CH, "lane": "code"}, [], sweep)


def _pauses(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM paused_runs ORDER BY id")]


def test_a_run_paused_at_its_slice_is_recorded_with_progress_and_a_look(monkeypatch, world):
    fake = Eval(rows=_rows(20, gained=2, lost=2))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = _sweep()
    assert _measure(sweep) == watch.PAUSED
    argv = fake.argvs[0]
    assert "--stop-at" in argv and "--resume" not in argv
    assert argv.count("--plan-s") == 2
    conn = world()
    try:
        (p,) = _pauses(conn)
        assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE tier = ?", (adopt.TIER,)).fetchone()[0] == 0
    finally:
        conn.close()
    assert p["state"] == "paused" and p["done"] == 40 and p["sweeps"] == 1
    (look,) = json.loads(p["looks"])
    assert look["decision"] == "continue" and look["gained"] == 2 and look["lost"] == 2
    assert any(line.startswith(f"{CH}: paused at 40/") and "look 1" in line for line in sweep.lines)


def test_a_paused_adopt_command_exits_75_as_a_paused_confirmation_does(monkeypatch, world):
    from harness.commands import adopt as adopt_cmd
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rows=_rows(5)))
    a = _ns(lane="code", challenger=CH, confirm=None, power=False, from_measurement=False)
    assert adopt_cmd.cmd_adopt(a) == watch.PAUSED == 75
    conn = world()
    try:
        assert [p["state"] for p in _pauses(conn)] == ["paused"]
    finally:
        conn.close()


def test_a_sweep_counts_a_paused_pair_as_neither_failed_nor_done(monkeypatch):
    from harness.commands import loop as loop_cmd
    got = iter([watch.PAUSED, 1])
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row, sweep: next(got))
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    failed = []
    rows = [{"name": "paused-one", "lane": "code"}, {"name": "broken-one", "lane": "code"}]
    assert loop_cmd._measure_all(argparse.Namespace(lane=""), rows, None, failed) == 1
    assert failed == ["measure broken-one"]


def test_a_deadline_kill_is_a_pause_not_a_verdict(monkeypatch, world):
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rows=_rows(5), timed_out=True))
    assert _measure() == watch.PAUSED
    conn = world()
    try:
        assert [p["state"] for p in _pauses(conn)] == ["paused"]
        assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE tier = ?", (adopt.TIER,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_the_next_measure_resumes_the_same_run_and_counts_the_sweep(monkeypatch, world):
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    fake.rows = _rows(30)
    _measure()
    first, second = fake.argvs
    assert "--resume" in second
    assert second[second.index("--out") + 1] == first[first.index("--out") + 1]
    assert second[second.index("--repeat") + 1] == first[first.index("--repeat") + 1]
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["sweeps"] == 2 and p["done"] == 60 and len(json.loads(p["looks"])) == 2


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/paused.py:find")
def test_a_changed_holdout_version_makes_the_pause_stale_and_restarts(monkeypatch, world):
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    conn = world()
    try:
        ident = json.loads(conn.execute("SELECT identity FROM paused_runs").fetchone()[0])
        conn.execute("UPDATE paused_runs SET identity = ?",
                     (json.dumps({**ident, "split_version": "0"}),))
        conn.commit()
    finally:
        conn.close()
    time.sleep(1.1)
    sweep = _sweep()
    _measure(sweep)
    first, second = fake.argvs
    assert "--resume" not in second
    assert second[second.index("--out") + 1] != first[first.index("--out") + 1]
    conn = world()
    try:
        states = [p["state"] for p in _pauses(conn)]
        why = _pauses(conn)[0]["why"]
    finally:
        conn.close()
    assert states == ["stale", "paused"]
    assert why.startswith("stale: split_version changed since the pause at 20/")
    assert any("stale: split_version changed" in line for line in sweep.lines)


def test_a_run_whose_checkpoint_is_another_exam_restarts_fresh(monkeypatch, world):
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    fake.rc = watch.STALE
    calls = []

    def stale_then_pause(argv, **kw):
        calls.append(argv)
        fake.rc = watch.STALE if len(calls) == 1 else watch.PAUSED
        return fake(argv, **kw)
    monkeypatch.setattr(measure_cmd, "_launch", stale_then_pause)
    time.sleep(1.1)
    _measure()
    assert "--resume" in calls[0] and "--resume" not in calls[1]
    conn = world()
    try:
        assert [p["state"] for p in _pauses(conn)] == ["stale", "paused"]
    finally:
        conn.close()


def test_a_finished_resume_spends_less_alpha_and_stores_planned_and_observed_seconds(monkeypatch, world):
    fake = Eval(rows=_rows(60, gained=1))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    rows = _rows(len(holdout.for_lane("code").holdout), gained=1)
    fake.rows, fake.rc = rows, 0
    data = {"run_id": None, "specs": {INC: INC, CH: CH}, "rows": rows,
            "summary": {INC: {"passed": 10, "total": 10}, CH: {"passed": 10, "total": 10}}}
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: data)
    _measure()
    conn = world()
    try:
        v = conn.execute("SELECT * FROM verdicts WHERE tier = ? ORDER BY id DESC", (adopt.TIER,)).fetchone()
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert v["planned_s_per_case"] == pytest.approx(3.0)
    assert v["observed_s_per_case"] == pytest.approx(4.0)
    assert json.loads(v["power"])["alpha"] < adopt.ALPHA
    assert p["state"] == "done"


def test_paused_measurements_go_first_and_once(world):
    conn = world()
    try:
        paused.save(conn, lane="code", inc_spec=INC, spec=CH, proposal="org/held", out="/x", ident={},
                    plan={}, done=1, total=2, looks=[])
        got = measure_cmd.resume_first(conn, [{"name": "org/new"}, {"name": "org/held"}])
    finally:
        conn.close()
    assert [r["name"] for r in got] == ["org/held", "org/new"]


# --- the looks themselves ---

def test_spending_is_zero_at_the_start_all_of_alpha_at_the_end_and_never_falls():
    seen = [looks.spent(t / 10, 0.05) for t in range(11)]
    assert seen[0] == 0.0 and seen[-1] == pytest.approx(0.05)
    assert seen == sorted(seen)
    assert looks.spent(0.25, 0.05) < 0.001


def _look(rows, plan=None, spent_before=0.0):
    plan = plan or {"repeat": 1, "effect": 0.2, "cells": 0, "cases": 0, "odds": (0.1, 0.02)}
    return looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=holdout.for_lane("code"),
                      plan=plan, alpha=0.05, spent_before=spent_before, n=1, spec=CH)


def test_an_early_lead_significant_at_alpha_does_not_stop_for_success():
    n = len(holdout.for_lane("code").holdout)
    look, verdict = _look(_rows(n // 5, gained=8))
    assert look.decision == "continue" and verdict is None
    assert look.nominal < 0.05


def test_an_overwhelming_lead_stops_for_success_with_the_spent_alpha():
    n = len(holdout.for_lane("code").holdout)
    look, verdict = _look(_rows(n // 2, gained=n // 2))
    assert look.decision == "success" and verdict.adopt


def test_a_challenger_behind_with_no_plausible_path_stops_for_futility():
    n = len(holdout.for_lane("code").holdout)
    look, verdict = _look(_rows(n - 5, lost=30))
    assert look.decision == "futility" and look.cp < looks.FUTILITY_CP
    assert verdict is not None and not verdict.adopt and verdict.why.startswith("futility:")


def test_a_challenger_ahead_is_never_stopped_for_futility():
    n = len(holdout.for_lane("code").holdout)
    look, _ = _look(_rows(n - 5, gained=3, lost=1), plan={"repeat": 1, "effect": 0.2, "odds": (0.0, 0.0)})
    assert look.cp < looks.FUTILITY_CP and look.decision == "continue"


def test_conditional_power_with_nothing_left_is_the_final_answer():
    assert looks.conditional_power(20, 2, 0, 0.1, 0.1, 0.05) == 1.0
    assert looks.conditional_power(3, 2, 0, 0.1, 0.1, 0.05) == 0.0


def test_a_resumed_plan_keeps_its_exam_and_takes_this_slices_budget():
    stored = power.Plan(2, 0.5, 10, 10, 0.2, 0.05, 0.8, 16, False, True, 0, "", side="holdout",
                        budget_s=7200.0, odds=(0.1, 0.02)).as_dict()
    fresh = power.Plan(1, 0.9, 10, 10, 0.2, 0.05, 0.8, 16, False, True, 0, "", budget_s=600.0,
                       deadline_s=900.0)
    got = measure_cmd._resumed_plan(json.loads(json.dumps(stored)), fresh)
    assert (got.repeat, got.side, got.budget_s, got.deadline_s, got.odds) == (2, "holdout", 600.0, 900.0, (0.1, 0.02))


def test_a_run_paused_on_request_halts_the_sweep(monkeypatch, world):
    fake = Eval(rows=_rows(5))

    def requested(argv, **kw):
        got = fake(argv, **kw)
        out = Path(argv[argv.index("--out") + 1])
        p = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        (out / watch.PROGRESS).write_text(json.dumps({**p, "why": "paused on request, 3 case(s) left"}),
                                          encoding="utf-8")
        return got
    monkeypatch.setattr(measure_cmd, "_launch", requested)
    sweep = _sweep()
    _measure(sweep)
    assert sweep.halted.startswith("paused at 10/")


def test_the_loop_starts_nothing_more_after_a_requested_pause_or_at_the_ceiling():
    from harness.commands import loop as loop_cmd
    sweep = _sweep()
    assert loop_cmd._held_back(sweep, 2) == "" and loop_cmd._held_back(None, 2) == ""
    sweep.halted = "paused at 1/2"
    assert loop_cmd._held_back(sweep, 2) == "a run was paused on request: 2 measurement(s) wait for the next sweep"
    assert loop_cmd._held_back(_sweep(0.0), 3).startswith("ceiling reached: 3")


def test_a_finished_resume_settles_its_pause_even_when_nothing_can_be_concluded(monkeypatch, world):
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    fake.rc = 0
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    assert _measure() == 1
    conn = world()
    try:
        assert [p["state"] for p in _pauses(conn)] == ["done"]
    finally:
        conn.close()
