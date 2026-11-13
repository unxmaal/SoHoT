"""A death between two durable writes leaves a state a rerun repairs, never a wrong answer: queue job exit and pid, eval run end, volume stop, adoption. #1758."""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from evals import run as R
from evals import watch
from harness import adopt, adoption_state as st, executors, run_state, runs, volume
from harness import memory_store as ms
from harness import workqueue as wq
from harness import job_procs, job_settle
from tests import conftest
from tests.test_adoption_state_1735 import STUDIO
from tests.test_pause_813 import Ticking, _args, _run, clock, quiet  # noqa: F401
from tests.test_volume import VOL, Queue, live, ops

CR = "two-durable-writes-with-no-repair-for-the-gap"
REPO = Path(__file__).resolve().parents[1]


class Died(BaseException):
    """A kill at this point: nothing after it in the process runs."""


def _die(*_a, **_k):
    raise Died()


def test_a_job_that_exited_0_before_its_worker_died_is_settled_by_its_exit_not_as_gone(monkeypatch):
    job = wq.add([sys.executable, "-c", "pass"], title="plain")
    with monkeypatch.context() as m:
        m.setattr(job_settle, "_settle_exit", _die)
        with pytest.raises(Died):
            wq.run_one(wq.get(job["id"]))
    assert wq.get(job["id"])["state"] == wq.RUNNING and not job_procs._pid_file(job["id"]).exists()
    assert job_settle._recover() == []
    got = wq.get(job["id"])
    assert (got["state"], got["rc"]) == (wq.DONE, 0), got


def test_a_failed_exit_recorded_before_the_worker_died_is_settled_failed_with_its_rc(monkeypatch):
    job = wq.add([sys.executable, "-c", "raise SystemExit(3)"], title="plain")
    with monkeypatch.context() as m:
        m.setattr(job_settle, "_settle_exit", _die)
        with pytest.raises(Died):
            wq.run_one(wq.get(job["id"]))
    job_settle._recover()
    got = wq.get(job["id"])
    assert (got["state"], got["rc"]) == (wq.FAILED, 3), got
    assert not executors.exit_file(job_procs._pid_file(job["id"])).exists()


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/executors.py:exit_record:except")
def test_no_exit_record_reads_none_a_recorded_0_reads_0_and_an_unreadable_one_raises(tmp_path):
    pid_file = tmp_path / "0001.pid"
    assert executors.exit_record(pid_file) is None
    executors.exit_file(pid_file).write_text("0 123.5", encoding="utf-8")
    assert executors.exit_record(pid_file) == (0, 123.5)
    executors.exit_file(pid_file).write_text("torn", encoding="utf-8")
    with pytest.raises(ValueError):
        executors.exit_record(pid_file)


_WORKER = textwrap.dedent("""
    import os, sys
    from harness import executors
    from harness import job_procs
    mark, child_at = sys.argv[1], sys.argv[2]
    real = job_procs.spawn_group
    def spawn(argv, cwd, stdout, env):
        child = real(argv, cwd, stdout, env)
        open(child_at, "w").write(str(child.pid))
        return child
    job_procs.spawn_group = spawn
    def died(_pid_file):
        os._exit(9)
    executors.started_file = died
    executors.Host().run({"id": 77}, [sys.executable, "-c", f"open({mark!r}, 'w').write('ran')"])
""")


@pytest.mark.skipif(sys.platform == "win32", reason="no exec: Windows runs the job ungated")
def test_a_worker_that_dies_between_the_spawn_and_the_pid_write_leaves_no_job_running(tmp_path):
    mark, child_at = tmp_path / "ran", tmp_path / "child"
    got = subprocess.run([sys.executable, "-c", _WORKER, str(mark), str(child_at)], cwd=REPO, timeout=60)
    assert got.returncode == 9
    pid = int(child_at.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 10
    while wq.alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    time.sleep(0.5)
    assert not mark.exists(), "the job ran with no pid file for _recover to find"
    assert not wq.alive(pid)


@pytest.mark.skipif(sys.platform == "win32", reason="no exec: Windows runs the job ungated")
def test_a_pid_write_that_fails_in_a_live_worker_leaves_no_gate_waiting(monkeypatch, tmp_path):
    seen = {}
    real = wq.spawn_group

    def spawn(argv, cwd, stdout, env):
        seen["child"] = real(argv, cwd, stdout, env)
        return seen["child"]
    monkeypatch.setattr(job_procs, "spawn_group", spawn)
    monkeypatch.setattr(executors, "started_file", _die)
    with pytest.raises(Died):
        executors.Host().run({"id": 78}, [sys.executable, "-c", f"open({str(tmp_path / 'ran')!r}, 'w')"])
    assert seen["child"].poll() is not None and not (tmp_path / "ran").exists()


def test_a_gated_job_runs_its_command_and_its_pid_is_the_commands(tmp_path):
    out = tmp_path / "pid"
    job = wq.add([sys.executable, "-c", f"import os; open({str(out)!r}, 'w').write(str(os.getpid()))"], title="plain")
    done = wq.run_one(wq.get(job["id"]))
    assert done["state"] == wq.DONE, done
    assert out.read_text(encoding="utf-8").strip().isdigit()


def test_a_gated_command_that_cannot_start_says_so_with_rc_127(tmp_path):
    job = wq.add([str(tmp_path / "no-such-program")], title="plain")
    done = wq.run_one(wq.get(job["id"]))
    assert (done["state"], done["rc"]) == (wq.FAILED, 127), done
    assert "could not start" in Path(done["log"]).read_text(encoding="utf-8")


def test_a_torn_results_export_never_replaces_the_one_before_it(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    assert _run(monkeypatch, Ticking(clock), _args(out, stop_at=clock.now + 45.0)) == watch.PAUSED
    before = json.loads((out / "results.json").read_text(encoding="utf-8"))
    real = Path.write_text

    def torn(self, data, *a, **k):
        if self.name.startswith("results.json"):
            real(self, data[: len(data) // 2], *a, **k)
            raise Died()
        return real(self, data, *a, **k)
    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(Died):
        _run(monkeypatch, Ticking(clock), _args(out, resume=True))
    monkeypatch.setattr(Path, "write_text", real)
    assert json.loads((out / "results.json").read_text(encoding="utf-8")) == before


def test_a_run_stored_by_a_queued_eval_is_stored_with_its_job_or_not_at_all(monkeypatch, tmp_path, quiet, clock):
    job = wq.add(["uv", "run", "python", "-m", "evals.run"], title="eval")
    monkeypatch.setenv(wq.JOB_ENV, str(int(job["id"])))
    monkeypatch.setattr(wq, "link_run", _die)
    out = tmp_path / "run"
    with pytest.raises(Died):
        _run(monkeypatch, Ticking(clock), _args(out))
    conn = ms.connect()
    try:
        got = conn.execute("SELECT job_id FROM runs WHERE path = ?", (runs.path_key(out),)).fetchone()
    finally:
        conn.close()
    assert got is None or got["job_id"] == int(job["id"]), "a stored run its job cannot find"


def test_a_run_killed_after_its_store_and_before_its_last_progress_is_finished_by_its_resume(
        monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    first = Ticking(clock)
    real = watch.Progress.write

    def killed(self, state=run_state.W_RUNNING, why="", run_id=None):
        if run_id is not None:
            raise Died()
        return real(self, state, why, run_id)
    with monkeypatch.context() as m:
        m.setattr(watch.Progress, "write", killed)
        with pytest.raises(Died):
            _run(monkeypatch, first, _args(out))
    assert run_state.of(out, alive=lambda *a: False).name == run_state.CRASHED
    assert run_state.CRASHED in run_state.RESUMABLE
    again = Ticking(clock)
    assert _run(monkeypatch, again, _args(out, resume=True)) == 0
    assert again.ran == [] and run_state.of(out, alive=lambda *a: False).name == run_state.DONE
    conn = ms.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE path = ?", (runs.path_key(out),)).fetchone()[0] == 1
    finally:
        conn.close()


def test_a_volume_stop_killed_while_it_waits_leaves_a_record_that_start_resumes_from(monkeypatch):
    m, q = live(), Queue()

    def quiesce():
        q.quiesce()
        raise Died()
    o = ops(m, q)
    o.quiesce = quiesce
    o.paused = lambda: q.paused
    with pytest.raises(Died):
        volume.stop(VOL, o)
    assert q.paused
    assert volume.start(ops(m, q))["resumed"] is True
    assert not q.paused and not volume.state_path().exists()


def test_a_volume_stop_that_cannot_quiesce_leaves_no_record(monkeypatch):
    from harness import quiesce as qmod
    m, q = live(), Queue()

    def quiesce():
        raise qmod.NotQuiesced("a job outlived the deadline")
    o = ops(m, q)
    o.quiesce = quiesce
    o.paused = lambda: q.paused
    with pytest.raises(volume.VolumeError, match="nothing stopped"):
        volume.stop(VOL, o)
    assert not volume.state_path().exists()


@pytest.fixture
def conn(monkeypatch):
    conftest.stand_in_machine(monkeypatch, STUDIO)
    c = ms.connect()
    ms.remember_machine(c)
    c.commit()
    yield c
    c.close()


@pytest.mark.gauntlet(CR, site="harness/adopt.py:record")
@pytest.mark.parametrize("why", [st.Lost("another writer moved the lane"), Died()])
def test_an_adoption_that_loses_or_dies_leaves_no_verdict_that_says_it_won(conn, monkeypatch, why):
    def move(*_a, **_k):
        raise why
    monkeypatch.setattr(st, "move", move)
    with pytest.raises(type(why)):
        adopt.record(conn, adopt.Verdict("music", "org/old", "org/new", True, "won", adopt.BY_HAND, votes=12))
    conn.commit()  # the caller's next write on this connection must not carry the lost verdict with it
    other = ms.connect()
    try:
        got = other.execute("SELECT v.outcome FROM verdicts v JOIN candidates c ON c.id = v.candidate_id "
                            "WHERE c.spec = ?", ("org/new",)).fetchall()
    finally:
        other.close()
    assert [r["outcome"] for r in got] == []


def test_an_adoption_that_wins_commits_its_verdict_with_it(conn):
    vid = adopt.record(conn, adopt.Verdict("music", "org/old", "org/new", True, "won", adopt.BY_HAND, votes=12))
    other = ms.connect()
    try:
        assert other.execute("SELECT outcome FROM verdicts WHERE id = ?", (vid,)).fetchone()["outcome"] == "measured"
        assert other.execute("SELECT COUNT(*) FROM adoptions WHERE verdict_id = ?", (vid,)).fetchone()[0] == 1
    finally:
        other.close()
