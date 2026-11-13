"""Every stored pid is judged by harness/proc_identity: a reused pid is never taken for the process that held it (#1820)."""
import ast
import os
import re
import subprocess
import sys
import time

import pytest

from harness import gateway_switch_state as st
from harness import paths, proc_identity, repo
from harness import workqueue as wq

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="process groups and start times are POSIX here")
#: Where a module reads a process's start time itself instead of asking proc_identity.
_OWN_READ = re.compile(r"KERN_PROC_PID|/proc/\{[^}]*\}/stat\b|lstart")
#: The one reader allowed besides proc_identity: switch rows claimed before #1820 hold a ps lstart.
_LEGACY = {"harness/gateway_switch_state.py": {"lstart"}}


def _earlier(started: str) -> str:
    """An earlier start on the same clock: a pid reused by a process that started at another time."""
    whole, dot, frac = started.partition(".")
    return f"{int(whole) - 100}{dot}{frac}"


@pytest.fixture()
def leader():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    yield p
    p.kill()
    p.wait()


def test_a_switch_row_carries_proc_identity_and_a_reused_pid_is_not_the_switch(leader):
    real = proc_identity.identity(leader.pid)
    assert real["started"] and st.started(leader.pid) == real["started"]
    assert st.me() == proc_identity.identity(os.getpid())
    assert st.alive(real) is True
    assert st.alive({**real, "started": _earlier(real["started"])}) is False
    if sys.platform != "win32":
        assert st.alive({**real, "pgid": real["pgid"] + 1}) is False


@POSIX
def test_a_switch_row_claimed_before_1820_with_a_ps_start_time_is_still_read(leader):
    lstart = st._lstart(leader.pid)
    assert lstart and not lstart.replace(".", "").isdigit()
    row = {"pid": leader.pid, "pgid": leader.pid, "started": lstart}
    assert st.alive(row) is True
    assert st.alive({**row, "started": "Thu Jan  1 00:00:00 1970"}) is False
    assert st.alive({**row, "pgid": leader.pid + 1}) is False


@POSIX
@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/gateway_switch_state.py:_lstart:except")
def test_a_ps_that_cannot_answer_leaves_an_old_switch_row_unjudged_not_dead(monkeypatch, leader):
    def hung(*a, **k):
        raise subprocess.TimeoutExpired("ps", st.PS_TIMEOUT_S)
    row = {"pid": leader.pid, "pgid": leader.pid, "started": "Thu Jan  1 00:00:00 1970"}
    monkeypatch.setattr(st.subprocess, "run", hung)
    assert st._lstart(leader.pid) == ""
    assert st.alive(row) is None


def test_a_job_pid_reused_by_another_group_leader_is_not_the_jobs_process(leader):
    from harness import executors
    job = wq.add(["soh-batch-job"], title="batch")
    started = proc_identity.started(leader.pid)
    pid_file = wq._pid_file(job["id"])
    pid_file.write_text(str(leader.pid), encoding="utf-8")
    executors.started_file(pid_file).write_text(f"{leader.pid} {started}", encoding="utf-8")
    assert wq._pid_of(job["id"]) == leader.pid
    executors.started_file(pid_file).write_text(f"{leader.pid} {_earlier(started)}", encoding="utf-8")
    assert wq._pid_of(job["id"]) is None
    executors.started_file(pid_file).write_text(f"{leader.pid + 1} {_earlier(started)}", encoding="utf-8")
    assert wq._pid_of(job["id"]) == leader.pid, "a start time left for another pid is not this one's"


@pytest.mark.parametrize("late", [0.0, 0.5], ids=["prompt", "parent-writes-late"])
def test_a_jobs_pid_file_stays_a_bare_pid_an_older_release_reads_and_its_start_time_sits_beside_it(
        tmp_path, monkeypatch, late):
    from harness import executors, watchdog
    read = proc_identity.started
    monkeypatch.setattr(proc_identity, "started", lambda pid: (time.sleep(late), read(pid))[1])
    job = wq.add(["soh-batch-job"], title="batch")
    pid_file = wq._pid_file(job["id"])
    beside = executors.started_file(pid_file)
    # Host.run writes both files after Popen, the pid file last: the child waits for it before reading either. #1893.
    script = (f"import pathlib, time\np = pathlib.Path({str(pid_file)!r})\nend = time.monotonic() + 30\n"
              "while not (p.exists() and p.read_text().strip()) and time.monotonic() < end:\n    time.sleep(0.01)\n"
              f"print(repr(p.read_text())); print(pathlib.Path({str(beside)!r}).read_text())")
    with open(tmp_path / "out.log", "w", encoding="utf-8") as out:
        child = executors.Host().run(job, [sys.executable, "-c", script], stdout=out)
    pid_text, started_line = (tmp_path / "out.log").read_text(encoding="utf-8").splitlines()[:2]
    assert int(ast.literal_eval(pid_text).strip()) == child.pid  # the parser of every release before #1820
    pid, started = started_line.split()
    assert pid == str(child.pid) and re.fullmatch(r"\d+(\.\d+)?", started)
    assert not pid_file.exists() and not beside.exists()
    pid_file.write_text(str(child.pid), encoding="utf-8")
    assert watchdog.Probes().job_pids()[pid_file.stem] == child.pid


def test_no_module_reads_a_process_start_time_but_proc_identity():
    found = {}
    for rel in repo.names(paths.REPO, "harness", "evals", "scripts"):
        if not rel.endswith(".py") or rel == "harness/proc_identity.py":
            continue
        hits = set(_OWN_READ.findall((paths.REPO / rel).read_text(encoding="utf-8"))) - _LEGACY.get(rel, set())
        if hits:
            found[rel] = sorted(hits)
    assert found == {}, f"read a process's identity through harness/proc_identity, not by hand: {found}"
