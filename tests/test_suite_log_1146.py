"""A cancelled check-macos run still says where its time went and what was running; a much slower test is named (#1146)."""
import os
import time
from types import SimpleNamespace

import pytest

from harness import suite_time
from tests import conftest


def _xml(path, cases):
    body = "".join(f'<testcase classname="tests.test_a" name="{n}" time="{s}"/>' for n, s in cases.items())
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite></testsuites>', encoding="utf-8")
    return path


@pytest.fixture
def logged(tmp_path, monkeypatch):
    log = tmp_path / "times.tsv"
    monkeypatch.setattr(conftest, "_test_log", {})
    monkeypatch.setenv(conftest.TEST_LOG_ENV, str(log))
    conftest.pytest_configure(SimpleNamespace())
    yield log
    conftest.pytest_unconfigure(SimpleNamespace())


def _report(nodeid, when, duration):
    return SimpleNamespace(nodeid=nodeid, when=when, duration=duration)


def test_each_finished_test_is_logged_with_its_three_phases_and_a_started_one_stays_running(logged):
    conftest.pytest_runtest_logstart("tests/test_a.py::done", ("", 0, ""))
    for when, s in (("setup", 0.5), ("call", 2.0), ("teardown", 0.25)):
        conftest.pytest_runtest_logreport(_report("tests/test_a.py::done", when, s))
    conftest.pytest_runtest_logstart("tests/test_a.py::hung", ("", 0, ""))
    conftest.pytest_runtest_logreport(_report("tests/test_a.py::hung", "setup", 0.1))
    done, running, last = suite_time.log_times(logged)
    assert done == {"tests/test_a.py::done": 2.75}
    assert list(running) == ["tests/test_a.py::hung"] and last >= running["tests/test_a.py::hung"]
    assert os.environ.get(conftest.TEST_LOG_ENV) is None


def test_a_worker_writes_no_log_and_the_variable_is_not_inherited(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest, "_test_log", {})
    monkeypatch.setenv(conftest.TEST_LOG_ENV, str(tmp_path / "times.tsv"))
    conftest.pytest_configure(SimpleNamespace(workerinput={}))
    conftest.pytest_runtest_logstart("tests/test_a.py::t", ("", 0, ""))
    assert not (tmp_path / "times.tsv").exists() and conftest.TEST_LOG_ENV not in os.environ


def test_a_pytest_a_test_starts_does_not_inherit_the_junit_path(monkeypatch):
    monkeypatch.setattr(conftest, "_test_log", {})
    monkeypatch.setenv("PYTEST_ADDOPTS", "--durations=60 --junitxml=/tmp/junit.xml --junit-xml /tmp/b.xml -x")
    conftest.pytest_configure(SimpleNamespace())
    assert os.environ["PYTEST_ADDOPTS"] == "--durations=60 -x"


def test_a_run_with_no_junit_reports_from_the_log_and_names_what_was_running(tmp_path, capsys):
    now = time.time()
    log = tmp_path / "times.tsv"
    log.write_text(f"{now - 100:.3f}\tstart\t\ttests/test_a.py::hung\n"
                   f"{now - 50:.3f}\tstart\t\ttests/test_a.py::ok\n"
                   f"{now:.3f}\tend\t3.500\ttests/test_a.py::ok\n"
                   "garbage\n" f"{now:.3f}\tend\tnot-a-number\ttests/test_a.py::x\n", encoding="utf-8")
    assert suite_time.main([str(tmp_path / "none.xml"), "--log", str(log)]) == 0
    out = capsys.readouterr().out
    assert "the run did not finish" in out and "1 tests, 3.5 s" in out
    assert "still running when the log ends: 1" in out and "100.0s  tests/test_a.py::hung" in out


def test_only_a_test_both_much_slower_and_many_seconds_slower_is_named():
    before = {"wait": 1.6, "grew": 10.0, "fast": 0.1, "gone": 1.0}
    now = {"wait": 121.0, "grew": 45.0, "fast": 20.0, "new": 300.0}
    assert suite_time.slower(now, before) == [("wait", 1.6, 121.0)]
    edge = suite_time.SLOWER_RATIO * 10.0
    assert suite_time.slower({"t": edge}, {"t": 10.0}, added_s=edge - 10.0) == [("t", 10.0, edge)]
    assert suite_time.slower({"t": edge - 0.01}, {"t": 10.0}, added_s=0) == []
    assert suite_time.slower({"t": 40.0}, {"t": 10.0 - 1e-9}, ratio=1, added_s=30.0) == [("t", 10.0 - 1e-9, 40.0)]
    assert suite_time.slower({"t": 39.99}, {"t": 10.0}, ratio=1, added_s=30.0) == []


def test_the_comparison_prints_a_github_warning_per_slower_test(tmp_path, capsys):
    prev = _xml(tmp_path / "prev.xml", {"wait": 1.6, "same": 2.0})
    cur = _xml(tmp_path / "cur.xml", {"wait": 122.1, "same": 2.1})
    assert suite_time.main([str(cur), "--against", str(prev)]) == 0
    out = capsys.readouterr().out
    assert "::warning title=Slower test::tests/test_a.py::wait: 1.6 s before, 122.1 s now" in out
    assert out.count("::warning") == 1
    assert suite_time.main([str(cur), "--against", str(tmp_path / "none.xml")]) == 0
    assert "no earlier run to compare" in capsys.readouterr().out


def test_a_refused_warm_up_in_the_suite_fails_at_once():
    """Two tests sat out the whole GATEWAY_DOWN_WAIT_S on every run until conftest cut it short (#1181)."""
    import httpx

    from evals import run
    from evals.runners.base import RunnerError

    class Refusing:
        asked = 0

        def warm(self):
            self.asked += 1
            try:
                raise httpx.ConnectError("[Errno 61] Connection refused")
            except httpx.ConnectError as exc:
                raise RunnerError("warm-up: gateway unreachable") from exc
    refusing = Refusing()
    with pytest.raises(RunnerError):
        run.warm(refusing)
    # Asked once more and gave up: the conftest clock ends the wait, so no poll interval is slept. #1423.
    assert refusing.asked == 2
