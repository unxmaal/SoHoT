"""One writer per eval run dir; a deploy-stopped yielding eval resumes; progress comes before the checkpoint. #1740."""
import json
import os
import subprocess
import sys

import pytest

from evals import run as R
from evals import watch
from harness import paths, run_state
from harness import workqueue as wq
from harness.watchdog import ProgressFiles
from tests.test_pause_813 import ROOT, Ticking, _args, _run, clock, quiet  # noqa: F401

LIVE_WRITER = ("import json, os, pathlib, sys, time\n"
               "out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)\n"
               "(out / 'progress.json').write_text(json.dumps({'state': 'running', 'pid': os.getpid(), "
               "'pgid': os.getpgid(0), 'done': 0, 'total': 4}))\n"
               "print('ready', flush=True); time.sleep(60)\n")
CLAIMER = ("import contextlib, sys, time\n"
           "from evals import watch\n"
           "held = contextlib.ExitStack()\n"
           "print(watch.claim(sys.argv[1], held) or 'ready', flush=True); time.sleep(60)\n")
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX here")


def _start(code: str, out):
    p = subprocess.Popen([sys.executable, "-c", code, str(out)], cwd=ROOT, stdout=subprocess.PIPE, text=True,
                         start_new_session=sys.platform != "win32")
    assert p.stdout.readline().strip() == "ready"
    return p


@pytest.fixture
def procs():
    got = []
    yield got
    for p in got:
        p.kill()
        p.wait()


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


@POSIX
def test_a_second_writer_on_a_dir_a_live_eval_writes_exits_non_zero(monkeypatch, tmp_path, quiet, clock, capsys,
                                                                    procs):
    out = tmp_path / "run"
    procs.append(_start(LIVE_WRITER, out))
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) != 0
    assert second.ran == []
    assert watch.read_progress(out)["pid"] == procs[0].pid
    assert not (out / watch.CHECKPOINT).exists()
    assert str(procs[0].pid) in capsys.readouterr().err


def test_a_second_writer_loses_to_one_that_holds_the_dir_before_its_progress(monkeypatch, tmp_path, quiet, clock,
                                                                              procs):
    out = tmp_path / "run"
    out.mkdir()
    procs.append(_start(CLAIMER, out))
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out)) != 0
    assert second.ran == [] and not (out / watch.PROGRESS).exists() and not (out / watch.CHECKPOINT).exists()


def test_a_dir_whose_writer_cannot_be_told_alive_is_refused(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    out.mkdir()
    (out / watch.PROGRESS).write_text(json.dumps({"state": "migrating", "pid": 1}), encoding="utf-8")
    assert run_state.of(out).name == run_state.UNKNOWN
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) != 0
    assert second.ran == []


@POSIX
def test_a_dir_whose_writer_died_resumes(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    first = Ticking(clock)
    assert _run(monkeypatch, first, _args(out, stop_at=clock.now + 25.0)) == watch.PAUSED
    pid = _dead_pid()
    got = {**watch.read_progress(out), "state": "running", "pid": pid, "pgid": pid}
    (out / watch.PROGRESS).write_text(json.dumps(got), encoding="utf-8")
    assert run_state.of(out).name == run_state.CRASHED
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) == 0
    assert second.ran and not set(first.ran) & set(second.ran)


def test_a_run_that_dies_in_setup_leaves_its_state_not_a_bare_checkpoint(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"

    def dies(*a, **k):
        assert (out / watch.CHECKPOINT).exists()
        raise SystemExit("died building its runner")

    monkeypatch.setattr(R, "build_runner", dies)
    with pytest.raises(SystemExit):
        R._execute(_args(out))
    got = run_state.of(out)
    assert got.name != run_state.UNKNOWN
    assert got.written == run_state.W_RUNNING and got.progress["pid"] == os.getpid()


def test_a_refused_rerun_leaves_the_paused_state_it_found(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    assert _run(monkeypatch, Ticking(clock), _args(out, stop_at=clock.now + 25.0)) == watch.PAUSED
    before = (out / watch.PROGRESS).read_bytes()
    assert _run(monkeypatch, Ticking(clock), _args(out)) != 0
    assert (out / watch.PROGRESS).read_bytes() == before


def _progress(name: str, **rec):
    d = paths.runs() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / watch.PROGRESS).write_text(json.dumps({"total": 4, "done": 1, **rec}), encoding="utf-8")
    return d


def test_a_deploy_stopped_yielding_eval_resumes_from_its_dir():
    job = {"argv": [sys.executable, "-m", "evals.run", "--modality", "code", "--out", "elsewhere"]}
    mine = _progress("20261112-000000-confirm-code", state="yielding", pid=4242, pgid=4242)
    _progress("20261112-000001-other", state="running", pid=5151, pgid=5151)
    _progress("20261112-000002-garbled", state="migrating", pid=6161)
    assert wq._stopped_argv(job, {4242, 4243}) == wq.resume_argv(job["argv"], mine)


def test_a_stopped_argv_names_no_dir_when_none_is_its_own():
    job = {"argv": [sys.executable, "-m", "evals.run", "--modality", "code"]}
    _progress("20261112-000001-other", state="running", pid=5151, pgid=5151)
    assert wq._stopped_argv(job, {4242}) is None


@POSIX
def test_the_watchdog_clears_a_pause_left_in_a_dead_runs_dir_and_keeps_a_paused_ones(tmp_path):
    pid = _dead_pid()
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    (crashed / watch.PROGRESS).write_text(json.dumps({"state": "running", "pid": pid, "pgid": pid}), encoding="utf-8")
    paused = tmp_path / "paused"
    paused.mkdir()
    (paused / watch.PROGRESS).write_text(json.dumps({"state": "paused", "pid": pid, "pgid": pid}), encoding="utf-8")
    for d in (crashed, paused):
        watch.ask_pause(d, "memory_pressure")
    assert run_state.of(crashed).name == run_state.CRASHED
    assert ProgressFiles(roots=[tmp_path]).runs() == []
    assert not (crashed / watch.PAUSE_FILE).exists()
    assert watch.pause_reason(paused) == "memory_pressure"
