"""Every stored pid is judged by harness/proc_identity: a reused pid is never taken for the process that held it (#1820)."""
import os
import re
import subprocess
import sys

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


@POSIX
def test_a_switch_row_carries_proc_identity_and_a_reused_pid_is_not_the_switch(leader):
    real = proc_identity.identity(leader.pid)
    assert real["started"] and st.started(leader.pid) == real["started"]
    assert st.me() == proc_identity.identity(os.getpid())
    assert st.alive(real) is True
    assert st.alive({**real, "started": _earlier(real["started"])}) is False
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


@POSIX
def test_a_job_pid_reused_by_another_group_leader_is_not_the_jobs_process(leader):
    job = wq.add(["soh-batch-job"], title="batch")
    started = proc_identity.started(leader.pid)
    wq._pid_file(job["id"]).write_text(f"{leader.pid} {started}", encoding="utf-8")
    assert wq._pid_of(job["id"]) == leader.pid
    wq._pid_file(job["id"]).write_text(f"{leader.pid} {_earlier(started)}", encoding="utf-8")
    assert wq._pid_of(job["id"]) is None


@POSIX
def test_a_jobs_pid_file_records_its_start_time_and_the_watchdog_still_reads_the_pid(tmp_path):
    from harness import executors, watchdog
    job = wq.add(["soh-batch-job"], title="batch")
    pid_file = wq._pid_file(job["id"])
    script = f"import pathlib; print(pathlib.Path({str(pid_file)!r}).read_text())"
    with open(tmp_path / "out.log", "w", encoding="utf-8") as out:
        child = executors.Host().run(job, [sys.executable, "-c", script], stdout=out)
    recorded = (tmp_path / "out.log").read_text(encoding="utf-8").split()
    assert recorded[0] == str(child.pid) and len(recorded) == 2 and re.fullmatch(r"\d+(\.\d+)?", recorded[1])
    pid_file.write_text(" ".join(recorded), encoding="utf-8")
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
