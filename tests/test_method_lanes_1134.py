"""#1134: the measure planner schedules a method only on a lane it runs, and --plan-s follows the requested candidates."""
import argparse

import pytest

from evals import run as R
from evals.core import Case
from harness import heartbeat, lanes, methods, repo_gate
from harness import memory_store as ms
from harness.commands import loop
from harness.commands import measure as measure_cmd


@pytest.fixture
def conn(tmp_path):
    c = ms.connect(tmp_path / "s.db")
    yield c
    c.close()


def _screened(conn, name, lane):
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane))
    ms.decide(conn, name, "screened", tier=ms.SCREEN, detail="ok")


def _queue(conn, monkeypatch, want, held):
    monkeypatch.setattr(repo_gate, "active", lambda: held)
    monkeypatch.setattr(heartbeat, "note", lambda k, v: None)
    return loop.measure_queue(conn, want, 0, room=lambda r: (True, None, ""), say=lambda s: None)


def _runs(name, lane):
    """evals.run's own answer: does `name` have a case of `lane` it can run?"""
    return bool(R.cases_for(name, [Case(id="c", modality=lane, prompt="p")]))


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("want", ["", *lanes.ALL])
def test_the_measure_planner_puts_no_method_on_a_lane_evals_run_would_skip(conn, monkeypatch, want, held):
    for m in methods.REGISTRY.values():
        for filed in lanes.ALL:
            _screened(conn, m.compose(f"org/{filed}-base"), filed)
    _screened(conn, "org/plain", "code")
    planned = []
    for row in _queue(conn, monkeypatch, want, held):
        a = repo_gate.args_for(argparse.Namespace(lane=want), row)
        planned.append((row["name"], measure_cmd.lane_for(row, a.lane)))
    bad = [(n, lane) for n, lane in planned if methods.is_method(n) and not _runs(n, lane)]
    assert bad == []
    if not want or methods.applicable(want):
        assert any(methods.is_method(n) for n, _ in planned), "the planner planned no method at all"
    if held and not want:
        assert ("org/plain", "repo") in planned, "the gate still puts a plain code model on the repo lane"


def test_a_plan_method_filed_under_code_is_not_scheduled_on_the_repo_lane(conn, monkeypatch):
    _screened(conn, "plan:llamacpp:Ornith-1.5-35B-Q4_K_M", "code")
    got = [(r["name"], measure_cmd.lane_for(r, repo_gate.args_for(argparse.Namespace(lane=""), r).lane))
           for r in _queue(conn, monkeypatch, "", True)]
    assert got == [("plan:llamacpp:Ornith-1.5-35B-Q4_K_M", "code")]
    assert repo_gate.blocked(conn, {"name": "plan:llamacpp:Ornith-1.5-35B-Q4_K_M", "lane": "code"}) == ""
    assert _queue(conn, monkeypatch, "repo", True) == []


def test_runs_in_reads_the_method_s_own_lanes():
    plan = methods.REGISTRY["plan"]
    for lane in lanes.ALL:
        assert methods.runs_in("plan:org/x", lane) == (lane in plan.lanes)
    assert methods.runs_in("org/x", "repo")
    assert not methods.runs_in("best-of:zero:org/x", "code")


def test_measure_refuses_a_method_row_on_a_lane_it_cannot_run(monkeypatch, capsys):
    monkeypatch.setattr(measure_cmd, "_plan", lambda *a, **k: pytest.fail("planned a run it cannot make"))
    rc = measure_cmd._measure(argparse.Namespace(lane="repo"), {"name": "plan:org/x", "lane": "repo"}, [])
    assert rc == 0
    assert "does not run the repo lane" in capsys.readouterr().out


def test_plan_s_follows_the_requested_candidates_when_one_is_skipped(monkeypatch, tmp_path):
    from tests.test_pause_813 import Clock, Ticking, _args, _run
    from evals import environment, watch
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: argparse.Namespace(as_dict=lambda: {}))
    clock = Clock()
    monkeypatch.setattr(watch, "clock", clock)
    out = tmp_path / "run"
    runner = Ticking(clock)
    rc = _run(monkeypatch, runner, _args(out, candidates="trace:mflux:dev,org/x", plan_s=[99.0, 12.0]))
    assert rc == 0
    assert runner.ran
    assert watch.read_progress(out)["planned_s_per_case"] == {"org/x": 12.0}
