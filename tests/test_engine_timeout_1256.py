"""A case cut under a derived engine clock is rerun once at the engine's ceiling; the basis counts only generated cases (#1256)."""
import json
import subprocess
import time
from pathlib import Path

import pytest

from evals import run as R
from evals.core import Case
from evals.runners import process
from evals.runners.process import ProcessRunner
from harness import engine_timeout as et
from harness import engines, knobs, proc, reasons, screen
from harness import memory_store as ms
from tests.test_engine_timeout_708 import record

#: Seconds each stored case of the engine took (a derived clock rounds up to whole seconds); the candidate takes SLOW times that.
HISTORY_S = 0.3
SLOW = 5
CLOCK_S = 1.0


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(et, "FLOOR_S", 0.01)
    c = ms.connect()
    yield c
    c.close()


def fake_engine(seconds: float, ceiling: float = 10.0) -> engines.Engine:
    """A pii engine that takes `seconds` per case and marks the one name in the prompt."""
    return engines.Engine(name="fake/heavy", spec="fake:heavy", modality="pii", output_suffix=".json",
                          timeout=ceiling, argv=lambda prompt, out, params: ["fake", str(out), str(seconds)])


def fake_run(argv, timeout=None, **_):
    out, seconds = Path(argv[1]), float(argv[2])
    time.sleep(min(seconds, timeout))
    if seconds > timeout:
        raise subprocess.TimeoutExpired(argv, timeout)
    out.write_text(json.dumps({"spans": [[0, 5]]}), encoding="utf-8")
    return proc.Outcome(0, seconds, 0)


CASE = Case(id="name", modality="pii", prompt="Alice went home", params={"spans": [[0, 5]]})


def runner_for(conn, tmp_path, monkeypatch, seconds, ceiling=10.0):
    monkeypatch.setattr(process.proc, "run", fake_run)
    record(conn, "pii", "fake/light", [HISTORY_S] * et.MIN_CASES)
    r = ProcessRunner(fake_engine(seconds, ceiling), tmp_path)
    clocks = R.engine_timeouts("pii", [("fake:heavy", r, [CASE])])
    assert r.timeout == CLOCK_S < seconds
    return r, clocks


def test_a_correct_candidate_five_times_slower_than_the_engine_history_is_graded_not_cut(conn, tmp_path, monkeypatch):
    slow = SLOW * HISTORY_S
    r, clocks = runner_for(conn, tmp_path, monkeypatch, slow)
    cut_at = r.timeout
    first = r.run(CASE)
    assert first.passed and first.failure_class == "" and not first.limit
    assert first.metrics["engine_rerun_wait_s"] >= cut_at * 0.9
    assert first.seconds < slow + cut_at * 0.5, "the cut attempt is not the case's time"
    ((entry),) = r.reran
    assert entry["cut_at"] == cut_at and "timed_out" not in entry
    assert r.timeout == min(10.0, max(cut_at, float(-(-et.MARGIN * entry["seconds"] // 1))))
    second = r.run(CASE)
    assert second.passed and len(r.reran) == 1 and "engine_rerun_wait_s" not in second.metrics
    got = R.engine_reruns(clocks, [("fake:heavy", r, [CASE])])["fake/heavy"]
    assert got["reran"] == r.reran and got["ended_at"] == r.timeout and got["from"] == "measured"


def test_a_wedged_candidate_is_still_cut(conn, tmp_path, monkeypatch):
    r, _ = runner_for(conn, tmp_path, monkeypatch, 60.0, ceiling=2.0)
    cut_at = r.timeout
    first = r.run(CASE)
    assert (first.failure_class, first.limit) == (reasons.TIMEOUT, "engine_timeout_s.pii>2")
    assert r.reran == [{"what": "", "cut_at": cut_at, "timed_out": True}]
    assert r.timeout == cut_at, "a rerun that timed out leaves the derived clock"
    second = r.run(CASE)
    assert (second.failure_class, second.limit) == (reasons.TIMEOUT, f"engine_timeout_s.pii>{cut_at:g}")
    assert len(r.reran) == 1


def test_reruns_zero_keeps_the_derived_clock_cut(conn, tmp_path, monkeypatch):
    r, _ = runner_for(conn, tmp_path, monkeypatch, SLOW * HISTORY_S)
    with knobs.rebind({"engine_timeout_reruns": 0}):
        row = r.run(CASE)
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, f"engine_timeout_s.pii>{CLOCK_S:g}")
    assert not getattr(r, "reran", None)


def test_a_case_at_the_ceiling_is_not_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(process.proc, "run", fake_run)
    r = ProcessRunner(fake_engine(5.0, ceiling=0.2), tmp_path)
    r.derived = True
    row = r.run(CASE)
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "engine_timeout_s.pii>0.2")
    assert not getattr(r, "reran", None)


def test_a_clock_a_caller_chose_is_not_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(process.proc, "run", fake_run)
    r = ProcessRunner(fake_engine(5.0, ceiling=10.0), tmp_path, timeout=0.2)
    row = r.run(CASE)
    assert (row.failure_class, row.limit) == (reasons.TIMEOUT, "engine_timeout_s.pii>0.2")
    assert not getattr(r, "reran", None)


def test_load_failures_do_not_count_toward_the_engine_basis(conn):
    record(conn, "image", "mflux/a", [3.0] * et.MIN_CASES, failure_class=reasons.LOAD_FAILED_LAYOUT)
    record(conn, "image", "mflux/b", [2.0] * et.MIN_CASES, failure_class=reasons.CRASHED)
    assert et.basis(conn, "image", "mflux/c", 900.0)["from"] == "ceiling"
    record(conn, "image", "mflux/d", [40.0] * (et.MIN_CASES - 1), failure_class=reasons.CONTENT_FAILED)
    record(conn, "image", "mflux/e", [50.0])
    got = et.basis(conn, "image", "mflux/c", 900.0)
    assert (got["from"], got["cases"], got["slowest"]) == ("measured", et.MIN_CASES, 50.0)


def test_the_screen_deadline_allows_the_rerun_at_the_ceiling(conn):
    from evals.run import SCREEN_CASES
    record(conn, "image", "mflux/z-image-turbo-q8", [30.0] * et.MIN_CASES)
    clock = et.MARGIN * 30.0
    assert screen.deadline_s("mflux:z-image-turbo") == SCREEN_CASES * clock + et.RERUNS * 900.0
    with knobs.rebind({"engine_timeout_reruns": 0}):
        assert screen.deadline_s("mflux:z-image-turbo") == SCREEN_CASES * clock


def test_the_reruns_knob_is_registered_and_binds_via_the_engine_timeout():
    k = knobs.KNOBS["engine_timeout_reruns"]
    assert k.default() == et.RERUNS == 1 and k.binds_via == "engine_timeout" and 0 in k.values
