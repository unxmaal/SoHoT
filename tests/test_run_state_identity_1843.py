"""#1843: an eval's progress file carries its process start time, so a pid reused in its group is not the eval."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from evals import watch
from harness import proc_identity, run_state, sweep_guard

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="process groups and start times are POSIX here")


def _earlier(started: str) -> str:
    whole, dot, frac = started.partition(".")
    return f"{int(whole) - 100}{dot}{frac}"


@pytest.fixture()
def leader():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    yield p
    p.kill()
    p.wait()


def _progress(d, **rec):
    d.mkdir(parents=True, exist_ok=True)
    (d / run_state.PROGRESS).write_text(json.dumps({"state": "running", "total": 4, **rec}), encoding="utf-8")
    return d


@POSIX
def test_a_pid_reused_by_another_group_leader_is_not_the_eval(tmp_path, leader):
    started = proc_identity.started(leader.pid)
    assert started
    rec = {"pid": leader.pid, "pgid": leader.pid}
    assert run_state.of(_progress(tmp_path / "same", **rec, pid_started=started)).name == run_state.RUNNING
    assert run_state.of(_progress(tmp_path / "reused", **rec, pid_started=_earlier(started))).name == run_state.CRASHED
    assert run_state.alive(leader.pid, leader.pid, _earlier(started)) is False


@POSIX
def test_a_progress_file_written_before_1843_is_judged_by_pid_and_group(tmp_path, leader):
    assert run_state.of(_progress(tmp_path / "old", pid=leader.pid, pgid=leader.pid)).name == run_state.RUNNING
    assert run_state.of(_progress(tmp_path / "moved", pid=leader.pid, pgid=leader.pid + 1)).name == run_state.CRASHED


@POSIX
def test_an_unread_start_time_falls_back_to_the_group_check_not_to_dead(monkeypatch, leader):
    started = proc_identity.started(leader.pid)
    monkeypatch.setattr(proc_identity, "_proc", lambda pid: None)
    assert run_state.alive(leader.pid, leader.pid, started) is True
    assert run_state.alive(leader.pid, leader.pid + 1, started) is False


def test_the_progress_writer_records_its_own_start_time(tmp_path):
    eye = watch.Watch(outdir=tmp_path)
    got = watch.Progress(tmp_path, eye, {}, total=1, done=0).write()
    assert got["pid_started"] == proc_identity.started(os.getpid())
    assert json.loads((tmp_path / run_state.PROGRESS).read_text(encoding="utf-8"))["pid_started"] == got["pid_started"]


@POSIX
def test_the_deploy_guard_run_as_a_file_judges_a_reused_pid_by_its_start_time(tmp_path, leader):
    """launchd.sh runs `python3 -I harness/sweep_guard.py HOME`: run_state finds proc_identity beside it."""
    code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('run_state', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(m.alive(int(sys.argv[2]), int(sys.argv[2]), sys.argv[3]))")
    started = proc_identity.started(leader.pid)
    path = os.path.join(os.path.dirname(sweep_guard.__file__), "run_state.py")
    for given, want in ((started, "True"), (_earlier(started), "False")):
        got = subprocess.run([sys.executable, "-I", "-S", "-c", code, path, str(leader.pid), given],
                             capture_output=True, text=True, timeout=30)
        assert got.stdout.strip() == want, got.stderr
