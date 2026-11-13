"""#1729: a run directory has one state from one function, and every safety reader sees a yielding run."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from evals import watch
from harness import paths, paused, run_state, sweep_guard, watchdog_observe

EVAL_CMD = "/opt/lh/deploy/.venv/bin/python3 -m evals.run --modality code --out /x/runs/measure-1"
INC, CH = "llamacpp:inc", "llamacpp:ch"


def _dir(root, name, state, *, pid=4242, pause=False, stop="", checkpoint=False, raw=None):
    d = root / name
    d.mkdir(parents=True)
    if raw is not None:
        (d / run_state.PROGRESS).write_text(raw, encoding="utf-8")
    elif state is not None:
        (d / run_state.PROGRESS).write_text(json.dumps({"state": state, "pid": pid, "pgid": pid, "total": 40}),
                                            encoding="utf-8")
    if pause:
        watch.ask_pause(d, "memory_stuck")
    if stop:
        watch.mark_stop(d, stop)
    if checkpoint:
        (d / run_state.CHECKPOINT).write_text(json.dumps({"identity": {}}) + "\n", encoding="utf-8")
    return d


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _live() -> dict:
    return {"pid": os.getpid(), "pgid": os.getpgid(0) if hasattr(os, "getpgid") else os.getpid()}


COMBOS = [
    # (written state, alive, pause file, stop file, raw progress, checkpoint) -> named state
    ("running", True, False, "", None, False, run_state.RUNNING),
    ("yielding", True, False, "", None, False, run_state.YIELDING),
    ("yielding", True, True, "", None, False, run_state.PAUSING),
    ("running", True, True, "", None, False, run_state.PAUSING),
    ("yielding", False, False, "", None, False, run_state.CRASHED),
    ("running", False, True, "", None, False, run_state.CRASHED),
    ("yielding", False, False, "no_progress", None, False, run_state.SIGNALLED),
    ("running", False, True, "overrun", None, False, run_state.SIGNALLED),
    ("paused", True, False, "", None, False, run_state.EXITING),
    ("done", True, False, "", None, False, run_state.EXITING),
    ("stopped", True, False, "", None, False, run_state.EXITING),
    ("paused", False, True, "", None, False, run_state.PAUSED),
    ("stopped", False, False, "incumbent_silent", None, False, run_state.STOPPED),
    ("done", False, True, "", None, False, run_state.DONE),
    ("running", None, False, "", None, False, run_state.UNKNOWN),
    ("yielding", None, False, "", None, False, run_state.UNKNOWN),
    ("frozen", True, False, "", None, False, run_state.UNKNOWN),
    ("", False, False, "", None, False, run_state.UNKNOWN),
    (None, False, False, "", "{torn", False, run_state.UNKNOWN),
    (None, False, False, "", "[1, 2]", False, run_state.UNKNOWN),
    (None, False, False, "", None, True, run_state.UNKNOWN),
    (None, False, False, "", None, False, run_state.ABSENT),
]


@pytest.mark.parametrize("written,live,pause,stop,raw,checkpoint,want", COMBOS)
def test_each_combination_of_the_inputs_maps_to_one_named_state(tmp_path, written, live, pause, stop, raw,
                                                                 checkpoint, want):
    d = _dir(tmp_path, "r", written, pause=pause, stop=stop, raw=raw, checkpoint=checkpoint)
    got = run_state.of(d, alive=lambda pid, pgid, started: live)
    assert got.name == want and got.name in run_state.STATES


def test_a_contradiction_is_never_read_as_not_running():
    """Unknown is a state every safety reader acts on: the watchdog may pause it and a deploy refuses on it."""
    assert run_state.UNKNOWN in run_state.LIVE and run_state.UNKNOWN in run_state.PAUSABLE
    assert run_state.UNKNOWN not in run_state.RESUMABLE
    assert set(run_state.LIVE).isdisjoint(run_state.RESUMABLE)


def test_the_reasons_come_from_the_stop_and_pause_files(tmp_path):
    d = _dir(tmp_path, "r", "yielding", stop="no_progress")
    assert run_state.of(d, alive=lambda pid, pgid, started: False).why == "no_progress"
    d = _dir(tmp_path, "s", "running", pause=True)
    assert run_state.of(d, alive=lambda pid, pgid, started: True).why == "memory_stuck"


@pytest.mark.skipif(sys.platform == "win32", reason="a process group is how a live run is told on POSIX")
def test_the_default_probe_tells_this_process_from_a_dead_one_and_a_reused_pid():
    me = _live()
    assert run_state.alive(me["pid"], me["pgid"]) is True
    assert run_state.alive(_dead_pid(), None) is False
    assert run_state.alive(me["pid"], me["pgid"] + 1) is False
    assert run_state.alive(me["pid"], None) is True
    assert run_state.alive(None, None) is None and run_state.alive("x", 1) is None


def test_the_progress_writer_refuses_a_state_no_reader_names(tmp_path):
    eye = watch.Watch(outdir=tmp_path)
    prog = watch.Progress(tmp_path, eye, {}, total=1, done=0)
    with pytest.raises(ValueError):
        prog.write("halted")
    eye.yielding_since = 1.0
    assert prog.write()["state"] == run_state.W_YIELDING


# --- every safety reader sees a yielding run -------------------------------------

def _yielding(root, name="20261111-000000-adopt-code", **kw):
    return _dir(root, name, "yielding", **kw)


def test_the_watchdog_has_a_yielding_run_to_pause(tmp_path):
    d = _yielding(tmp_path)
    (d / run_state.PROGRESS).write_text(json.dumps({"state": "yielding", **_live()}), encoding="utf-8")
    got = watchdog_observe.ProgressFiles([tmp_path]).runs()
    assert [r["_dir"] for r in got] == [str(d)]
    assert "pause file written" in watchdog_observe.ProgressFiles([tmp_path]).pause(got[0], "contention")


def test_a_deploy_refuses_while_a_yielding_eval_runs(tmp_path):
    runs = tmp_path / sweep_guard.RUNS
    _yielding(runs, "measure-1", pid=5151)
    got = sweep_guard.running(tmp_path, alive=lambda p: p == 5151, command_of=lambda p: EVAL_CMD)
    assert [(r["what"], r["pid"]) for r in got] == [("eval measure-1", 5151)]


@pytest.mark.parametrize("state", ["frozen", "done"])
def test_a_deploy_refuses_on_a_live_eval_whose_state_is_unknown_or_still_exiting(tmp_path, state):
    _dir(tmp_path / sweep_guard.RUNS, "measure-1", state, pid=5151)
    got = sweep_guard.running(tmp_path, alive=lambda p: p == 5151, command_of=lambda p: EVAL_CMD)
    assert [r["pid"] for r in got] == [5151]


def _abandon(root, state, pid):
    out = root / "20261111-000000-adopt-code"
    out.mkdir(parents=True)
    ck = watch.Checkpoint(out, {"modality": "code", "candidates": [INC, CH]})
    ck.add({"candidate": "inc", "case_id": "c1"}, 1.0)
    (out / run_state.PROGRESS).write_text(json.dumps({"state": state, "pid": pid, "pgid": pid, "total": 4}),
                                          encoding="utf-8")
    return out


def test_a_crashed_yielding_run_is_resumed(tmp_path):
    from harness import memory_store as ms
    out = _abandon(paths.runs(), "yielding", _dead_pid())
    conn = ms.connect()
    try:
        got = paused.abandoned(conn, paths.runs(), "code", INC, CH)
    finally:
        conn.close()
    assert got is not None and got["out"] == str(out)


def test_a_dead_run_whose_state_is_unknown_is_not_resumed(tmp_path):
    from harness import memory_store as ms
    _abandon(paths.runs(), "frozen", _dead_pid())
    conn = ms.connect()
    try:
        assert paused.abandoned(conn, paths.runs(), "code", INC, CH) is None
    finally:
        conn.close()


def test_a_deploy_guard_run_as_a_file_finds_the_state_module_beside_it(tmp_path):
    """launchd.sh runs `python3 -I harness/sweep_guard.py HOME`, where no package is importable."""
    (tmp_path / sweep_guard.RUNS).mkdir()
    got = subprocess.run([sys.executable, "-I", "-S", sweep_guard.__file__, str(tmp_path)], capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
