"""#1650: a plan refusal of either side of a paired measure is a harness limit, said once, never a failure."""
import argparse

import pytest

from evals import watch
from harness import context
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands.measure import Launched
from tests.test_resume_813 import Eval, _rows, _sweep

STEM = "Ornith-1.5-35B-Q4_K_M"
INC = f"llamacpp:{STEM}"
CH_STEM = "Chal-27B-Q4_K_M"
CH = f"llamacpp:{CH_STEM}"
WHY = "refused: 4 slots of 262144 tokens need 20.0 GiB of KV, 0.0 GiB fits"


@pytest.fixture
def world(monkeypatch, tmp_path):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    monkeypatch.setattr("harness.adopt.default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    monkeypatch.setattr(loop_cmd.repo_gate, "args_for", lambda a, row: a)
    monkeypatch.setattr(loop_cmd, "_gated", lambda row, want: "")
    conn = real(tmp_path / "d.db")
    for name in (CH, "llamacpp:Other-9B-Q4_K_M"):
        ms.record(conn, ms.Seen(name=name, source="t", lane="code", resolved=name))
        ms.decide(conn, name, "screened", tier=ms.SCREEN, reason="candidate")
    conn.close()
    return lambda: real(tmp_path / "d.db")


def _refuse(monkeypatch, *stems):
    monkeypatch.setattr(context, "refusal", lambda s, conn=None: WHY if s in stems else "")


def _ns():
    return argparse.Namespace(lane="", repeat=1, effect=0.4, power_budget_min=60.0)


def test_a_refused_incumbent_launches_nothing_in_its_lane_and_says_so_once(monkeypatch, world, capsys):
    _refuse(monkeypatch, STEM)
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep, failed = _sweep(), []
    rows = [{"name": CH, "lane": "code"}, {"name": "llamacpp:Other-9B-Q4_K_M", "lane": "code"}]
    assert loop_cmd._measure_all(_ns(), rows, sweep, failed) == 0
    assert fake.argvs == [] and failed == []
    said = [line for line in capsys.readouterr().out.splitlines() if f"plan:{STEM}" in line]
    assert len(said) == 1 and WHY in said[0] and "2 measurement(s) wait" in said[0]
    assert [line for line in sweep.lines if f"plan:{STEM}" in line] == [said[0].strip()]
    conn = world()
    try:
        assert ms.latest(conn, CH)["outcome"] == "screened", "the challengers wait, untouched"
    finally:
        conn.close()


def test_the_measure_itself_never_launches_against_a_refused_incumbent(monkeypatch, world):
    _refuse(monkeypatch, STEM)
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    sweep = _sweep()
    assert measure_cmd._measure(_ns(), {"name": CH, "lane": "code"}, [], sweep) == 0
    assert fake.argvs == []
    assert any(f"plan:{STEM}" in line for line in sweep.lines)


def _limit(conn, name):
    return dict(conn.execute("SELECT v.outcome, v.reason, v.until, v.failure_class FROM proposals p JOIN verdicts v "
                             "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def test_a_refused_challenger_is_a_limit_waiting_on_its_plan_not_a_failure(monkeypatch, world):
    _refuse(monkeypatch, CH_STEM)
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    failed = []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], _sweep(), failed) == 0
    assert fake.argvs == [] and failed == []
    conn = world()
    try:
        got = _limit(conn, CH)
    finally:
        conn.close()
    assert got == {"outcome": "declined", "reason": "limit", "until": f"plan:{CH_STEM}",
                   "failure_class": "plan_refused"}


def test_a_plan_refusal_exit_from_the_run_is_the_same_limit(monkeypatch, world):
    def refused_mid_run(argv, **kw):
        return Launched(1, f"{CH} is not served: {WHY}\n", False, 1.0)
    monkeypatch.setattr(measure_cmd, "_launch", refused_mid_run)
    failed = []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], _sweep(), failed) == 0
    assert failed == []
    conn = world()
    try:
        assert _limit(conn, CH)["until"] == f"plan:{CH_STEM}"
    finally:
        conn.close()


def test_an_incumbent_refusal_exit_from_the_run_is_no_failure_and_no_verdict(monkeypatch, world):
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: Launched(1, f"{INC} is not served: {WHY}", False, 1.0))
    failed = []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], _sweep(), failed) == 0
    assert failed == []
    conn = world()
    try:
        assert ms.latest(conn, CH)["outcome"] == "screened"
    finally:
        conn.close()


def test_with_the_refusal_cleared_the_lane_launches_as_before(monkeypatch, world):
    _refuse(monkeypatch)
    fake = Eval(rows=_rows(5))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    rows = [{"name": CH, "lane": "code"}, {"name": "llamacpp:Other-9B-Q4_K_M", "lane": "code"}]
    loop_cmd._measure_all(_ns(), rows, _sweep(), [])
    assert len(fake.argvs) == 2


def test_any_other_nonzero_exit_is_still_a_failure(monkeypatch, world):
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: Launched(1, "Traceback: boom", False, 1.0))
    failed = []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], _sweep(), failed) == 1
    assert failed == [f"measure {CH}"]


def test_a_paused_run_is_still_not_a_failure(monkeypatch, world):
    _refuse(monkeypatch)
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rows=_rows(5), rc=watch.PAUSED))
    failed = []
    assert loop_cmd._measure_all(_ns(), [{"name": CH, "lane": "code"}], _sweep(), failed) == 0
    assert failed == []
