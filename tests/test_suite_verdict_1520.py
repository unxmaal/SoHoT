"""A run that did not finish says whether it was a slow suite at N% or a hang, and names the hung test (#1520)."""
from types import SimpleNamespace

import pytest

from harness import suite_time
from tests import conftest


def test_the_hang_threshold_is_the_watchdogs_dump_time():
    assert suite_time.HANG_S == conftest.HANG_DUMP_S


def test_a_suite_still_finishing_tests_at_the_end_is_slow_at_its_share_done():
    done = {f"t{i}": 1.0 for i in range(88)}
    why = suite_time.verdict(done, {"slow": 990.0}, 999.0, 100, now=1000.0)
    assert why.startswith("slow suite at 88% (88 of 100 tests)"), why
    assert "longest in flight 10 s" in why


def test_a_test_in_flight_past_the_threshold_is_a_hang_named_by_its_id():
    h = suite_time.HANG_S
    why = suite_time.verdict({"a": 1.0}, {"tests/x.py::stuck": 1000.0 - h}, 999.0, 4, now=1000.0)
    assert why.startswith("hang: tests/x.py::stuck in flight") and "at 25% (1 of 4 tests)" in why, why
    assert suite_time.verdict({"a": 1.0}, {"x": 1000.0 - h + 1}, 999.0, 4, now=1000.0).startswith("slow suite")


def test_nothing_starting_or_ending_past_the_threshold_is_a_hang_with_nothing_in_flight():
    h = suite_time.HANG_S
    why = suite_time.verdict({"a": 1.0}, {}, 1000.0 - h, None, now=1000.0)
    assert why.startswith("hang: no test started or ended") and "total unknown" in why, why
    assert suite_time.verdict({"a": 1.0}, {}, 1000.0 - h + 1, None, now=1000.0).startswith("slow suite")


@pytest.fixture
def logged(tmp_path, monkeypatch):
    log = tmp_path / "times.tsv"
    monkeypatch.setattr(conftest, "_test_log", {})
    monkeypatch.setenv(conftest.TEST_LOG_ENV, str(log))
    conftest.pytest_configure(SimpleNamespace())
    yield log
    conftest.pytest_unconfigure(SimpleNamespace())


def test_the_log_records_how_many_tests_the_run_collected_once(logged):
    conftest.pytest_collection_finish(SimpleNamespace(items=[]))
    conftest.pytest_xdist_node_collection_finished(None, ["a", "b", "c"])
    conftest.pytest_xdist_node_collection_finished(None, ["a", "b", "c", "d"])
    assert suite_time.collected(logged) == 3
    conftest.pytest_collection_finish(SimpleNamespace(items=[1, 2]))
    assert suite_time.collected(logged) == 2


def test_a_cancelled_run_warns_slow_suite_at_its_share(tmp_path, capsys):
    log = tmp_path / "times.tsv"
    log.write_text("100.000\tcollected\t4\t\n"
                   "100.000\tstart\t\ttests/a.py::one\n101.000\tend\t1.000\ttests/a.py::one\n"
                   "101.000\tstart\t\ttests/a.py::two\n", encoding="utf-8")
    assert suite_time.main([str(tmp_path / "none.xml"), "--log", str(log), "--now", "103"]) == 0
    out = capsys.readouterr().out
    assert "::warning title=Did not finish::slow suite at 25% (1 of 4 tests)" in out
    assert suite_time.main([str(tmp_path / "none.xml"), "--log", str(log), "--now", str(101 + suite_time.HANG_S)]) == 0
    assert "::warning title=Did not finish::hang: tests/a.py::two in flight" in capsys.readouterr().out
