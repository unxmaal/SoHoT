"""A paused eval keeps its rows and resumes where it stopped; a run writes progress as it goes. #813, #810."""
import argparse
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import environment, watch
from evals import run as R
from evals.runners.base import BaseRunner
from harness import memory_store as ms
from harness import completion, runs

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def quiet(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {}))


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Ticking(BaseRunner):
    """Each case takes `each` seconds of the fake clock; `on_case` runs before the n-th case returns."""

    def __init__(self, clock, each=10.0, on_case=None):
        self.candidate = self.spec = "org/x"
        self.clock, self.each, self.on_case = clock, each, on_case
        self.ran = []

    def generate(self, case):
        self.ran.append(case.id)
        self.clock.now += self.each
        if self.on_case:
            self.on_case(len(self.ran))
        return "", 0


def _args(out, **kw):
    base = dict(screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
                modality="code", candidates="org/x", from_winners=False, gateway="http://gw.test",
                out=str(out), split="holdout", max_tokens=None, resume=False, stop_at=None,
                plan_s=None, budget_min=None)
    return argparse.Namespace(**{**base, **kw})


def _run(monkeypatch, runner, args):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    return R._execute(args)


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(watch, "clock", c)
    return c


def test_a_run_past_its_stop_time_pauses_with_its_rows_checkpointed_and_stored(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runner = Ticking(clock)
    rc = _run(monkeypatch, runner, _args(out, stop_at=clock.now + 45.0))
    assert rc == watch.PAUSED
    assert len(runner.ran) == 5
    _, rows = watch.read(out)
    assert [r["case_id"] for r in rows] == runner.ran
    got = watch.read_progress(out)
    assert got["state"] == "paused" and got["done"] == 5 and got["total"] > 5
    conn = ms.connect()
    try:
        run_id = got["run_id"]
        assert len(runs.rows(conn, run_id)) == 5
        receipt = json.loads(conn.execute("SELECT receipt FROM runs WHERE id = ?", (run_id,)).fetchone()[0])
    finally:
        conn.close()
    assert receipt["progress"]["state"] == "paused"


def test_a_resume_runs_only_the_cases_not_yet_done_and_stores_one_run(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    first = Ticking(clock)
    _run(monkeypatch, first, _args(out, stop_at=clock.now + 45.0))
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) == 0
    assert not set(first.ran) & set(second.ran)
    got = watch.read_progress(out)
    assert got["state"] == "done" and got["done"] == got["total"] == len(first.ran) + len(second.ran)
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert "progress" not in data["receipt"]
    assert len(data["rows"]) == got["total"]
    conn = ms.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert len(runs.rows(conn, got["run_id"])) == got["total"]
    finally:
        conn.close()


def test_a_resume_of_another_exam_is_stale_and_runs_nothing(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    _run(monkeypatch, Ticking(clock), _args(out, stop_at=clock.now + 25.0))
    again = Ticking(clock)
    budget = completion.budget("code")
    assert _run(monkeypatch, again, _args(out, resume=True, max_tokens=budget + 1)) == watch.STALE
    assert again.ran == []


def test_a_pause_file_in_the_run_dir_pauses_after_the_case_in_flight(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runner = Ticking(clock, on_case=lambda n: n == 3 and (out / watch.PAUSE_FILE).touch())
    assert _run(monkeypatch, runner, _args(out)) == watch.PAUSED
    assert len(runner.ran) == 3
    assert watch.read_progress(out)["why"].startswith("paused on request")


@pytest.mark.skipif(sys.platform == "win32", reason="no SIGUSR1")
def test_sigusr1_pauses_after_the_case_in_flight(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runner = Ticking(clock, on_case=lambda n: n == 2 and os.kill(os.getpid(), signal.SIGUSR1))
    assert _run(monkeypatch, runner, _args(out)) == watch.PAUSED
    assert len(runner.ran) == 2


def test_progress_is_written_after_every_case_with_what_a_watchdog_needs(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    seen = []
    runner = Ticking(clock, each=30.0)
    runner.on_case = lambda n: seen.append(watch.read_progress(out).get("done"))
    _run(monkeypatch, runner, _args(out, plan_s=[12.0]))
    assert seen[:3] == [0, 1, 2]
    got = watch.read_progress(out)
    assert got["planned_s_per_case"] == {"org/x": 12.0}
    assert got["observed_s_per_case"]["org/x"] == pytest.approx(30.0)
    assert got["pid"] == os.getpid() and got["specs"] == {"org/x": "org/x"}
    assert got["last_progress_at"] >= got["started_at"]
    assert got["pause_file"] == str(out / watch.PAUSE_FILE)


def test_a_stated_budget_is_the_plan_where_no_receipt_gives_one(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    _run(monkeypatch, Ticking(clock), _args(out, budget_min=60.0))
    got = watch.read_progress(out)
    assert got["planned_s_per_case"]["org/x"] == pytest.approx(3600.0 / got["total"])


def test_the_default_plan_is_the_candidates_stored_mean_here(store_run):
    budget = completion.budget("code")
    assert R.stored_seconds("code", "org/x", budget, ()) is None
    store_run("prior", "code", rows=[{"case_id": f"c{i}#1", "candidate": "org/x", "passed": True,
                                      "seconds": s, "peak_kb": 0, "detail": ""}
                                     for i, s in enumerate((4.0, 10.0))],
              specs={"org/x": "org/x"}, receipt={"max_tokens": budget})
    assert R.stored_seconds("code", "org/x", budget, ()) == pytest.approx(7.0)
    assert R.stored_seconds("code", "org/x", budget + 1, ()) is None


def test_plan_s_must_name_every_candidate(monkeypatch, tmp_path, quiet, clock):
    with pytest.raises(SystemExit, match="--plan-s given 2"):
        _run(monkeypatch, Ticking(clock), _args(tmp_path / "r", plan_s=[1.0, 2.0]))


def test_a_torn_last_checkpoint_line_is_ignored(tmp_path):
    ck = watch.Checkpoint(tmp_path, {"a": 1})
    ck.add({"case_id": "x"}, 1.0)
    with ck.path.open("a", encoding="utf-8") as f:
        f.write('{"row": {"case_')
    assert watch.read(tmp_path) == ({"a": 1}, [{"case_id": "x", "wall_s": 1.0}])
