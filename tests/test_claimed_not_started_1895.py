"""A job its worker claimed and has not started is not gone: settle, cancel, the deploy hold, lease loss and recovery tell the two apart. #1895."""
import os
import subprocess
import sys
import threading
import time

import pytest

from harness import deploy, job_claim, paths
from harness import workqueue as wq
from harness import job_procs, job_settle

WAIT_S = 30.0
QUICK = [sys.executable, "-c", ""]
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]
posix = pytest.mark.skipif(sys.platform == "win32", reason="a process's start time is read on POSIX only")


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    said = []
    monkeypatch.setattr(deploy, "_alert_here", said.append)
    return said


class Held:
    """wq.run_one in a thread, held after its claim and before its Popen until release()."""

    def __init__(self, monkeypatch, job):
        self.job, self.got, self.errors = job, [], []
        self.at, self.go = threading.Barrier(2, timeout=WAIT_S), threading.Event()
        real = wq.spawn_group

        def spawn(argv, cwd, stdout, env):
            self.at.wait()
            assert self.go.wait(WAIT_S), "the test never released the worker"
            return real(argv, cwd, stdout, env)
        monkeypatch.setattr(job_procs, "spawn_group", spawn)

        def work():
            try:
                self.got.append(wq.run_one(job))
            except BaseException as exc:  # noqa: BLE001 - raised in the test by finish()
                self.errors.append(exc)
                self.at.abort()
        self.thread = threading.Thread(target=work, name=f"held-{job['id']}")
        self.thread.start()
        self.at.wait()
        assert wq.get(job["id"])["state"] == wq.RUNNING and job_procs._pid_of(job["id"]) is None

    def release(self) -> None:
        self.go.set()

    def finish(self) -> dict:
        self.release()
        self.thread.join(WAIT_S * 2)
        assert not self.thread.is_alive(), "the worker never finished"
        if self.errors:
            raise self.errors[0]
        return self.got[0]


def _deploy_job(argv=QUICK) -> dict:
    return wq.add(argv, title="deploy x", kind=deploy.KIND, output="x" * 40, priority=deploy.PRIORITY,
                  cwd=str(paths.home()))


def test_settle_leaves_a_deploy_job_its_worker_claimed_and_has_not_started(monkeypatch):
    job = _deploy_job()
    held = Held(monkeypatch, job)
    try:
        got = deploy.settle()
        state = wq.get(job["id"])["state"]
    finally:
        held.finish()
    assert got == [] and state == wq.RUNNING


def _release_when_starting(monkeypatch, held: Held) -> list:
    """Let the worker go on to its Popen once the reader under test has seen the job starting."""
    real, seen = job_claim.starting, []

    def spy(job_id):
        got = real(job_id)
        seen.append(got)
        if got:
            held.release()
        return got
    monkeypatch.setattr(job_claim, "starting", spy)
    return seen


def test_settle_leaves_a_recorded_deploy_whose_job_its_worker_has_not_started(monkeypatch):
    job = _deploy_job()
    held = Held(monkeypatch, job)
    try:
        with wq._store() as c:
            did = deploy._insert(c, job["output"], int(job["id"]), paths.home(), "", time.time())
        got = deploy.settle()
        with wq._store() as c:
            outcome = c.execute("SELECT outcome FROM deploys WHERE id = ?", (did,)).fetchone()["outcome"]
        state = wq.get(job["id"])["state"]
    finally:
        held.finish()
    assert got == [] and state == wq.RUNNING and outcome == ""


COPY = "a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates"


@pytest.mark.gauntlet(COPY, site="harness/job_claim.py:mark")
def test_a_claim_whose_worker_is_gone_is_still_settled_failed():
    job = _deploy_job()
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    dead = subprocess.Popen(QUICK)
    dead.wait()
    job_claim.mark(job["id"], dead.pid)
    got = deploy.settle()
    assert [d["outcome"] for d in got] == [deploy.INTERRUPTED]
    assert wq.get(job["id"])["state"] == wq.FAILED


@posix
@pytest.mark.gauntlet(COPY, site="harness/job_claim.py:mark")
def test_a_claim_whose_worker_pid_was_reused_is_gone():
    job = _deploy_job()
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    job_claim.path(job["id"]).write_text(
        f'{{"pid": {os.getpid()}, "pgid": {os.getpgid(0)}, "started": "1.000000"}}', encoding="utf-8")
    assert not job_claim.starting(job["id"])
    job_settle._recover()
    assert wq.get(job["id"])["state"] == wq.FAILED


def test_recovery_leaves_a_job_its_worker_claimed_and_has_not_started(monkeypatch):
    job = wq.add(QUICK, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    try:
        job_settle._recover()
        state = wq.get(job["id"])["state"]
    finally:
        done = held.finish()
    assert state == wq.RUNNING and done["state"] == wq.DONE


def test_the_claim_mark_is_gone_once_the_job_ends_or_the_claim_loses(monkeypatch):
    job = wq.add(QUICK, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    assert job_claim.path(job["id"]).exists()
    assert held.finish()["state"] == wq.DONE and not job_claim.path(job["id"]).exists()
    other = wq.add(QUICK, title="claimed elsewhere", cwd=str(paths.home()))
    assert wq._claim(dict(other), wq.log_dir() / "x.log")
    assert wq.run_one(other) is None and not job_claim.path(other["id"]).exists()


@posix
def test_cancel_waits_for_a_starting_job_and_stops_it(monkeypatch):
    job = wq.add(SLEEPER, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    seen = _release_when_starting(monkeypatch, held)
    try:
        got = wq.cancel(job["id"], grace=5.0)
    finally:
        done = held.finish()
    assert True in seen and got["state"] == wq.CANCELLED and done["state"] == wq.CANCELLED


@posix
def test_a_lost_lease_stops_a_job_that_was_still_starting(monkeypatch):
    job = wq.add(SLEEPER, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    seen = _release_when_starting(monkeypatch, held)
    try:
        job_settle._lease_lost(job, "lapsed in the test")
    finally:
        done = held.finish()
    assert True in seen and done["rc"] != 0


@posix
def test_the_deploy_hold_stops_a_job_that_was_still_starting(monkeypatch):
    monkeypatch.setattr(job_procs, "_tree", lambda pid: [(pid, "")])
    job = wq.add(SLEEPER, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    seen = _release_when_starting(monkeypatch, held)
    try:
        said = wq.hold_for_deploy(grace=5.0)
    finally:
        held.finish()
        wq.release_for_deploy()
    assert True in seen and any(s.startswith(f"job {job['id']} stopped for the deploy") for s in said)
    assert wq.get(job["id"])["state"] == wq.PENDING


def test_a_deploy_quiesce_counts_a_job_that_is_still_starting(monkeypatch):
    monkeypatch.setattr(deploy, "QUIESCE_TIMEOUT_S", 0.0)
    monkeypatch.setattr("harness.cuts.cut", lambda *a, **k: None)
    job = wq.add(QUICK, title="measure", cwd=str(paths.home()))
    held = Held(monkeypatch, job)
    try:
        with wq._store() as c, open(wq.log_dir() / "quiesce.log", "w", encoding="utf-8") as log:
            left = deploy._quiesce(c, 999999, log)
    finally:
        held.finish()
    assert left.startswith(f"job {wq.label(job['id'])} still running here")


def test_a_claim_with_no_mark_an_older_release_made_is_settled_failed_as_before():
    job = _deploy_job()
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    assert not job_claim.path(job["id"]).exists()
    assert [d["outcome"] for d in deploy.settle()] == [deploy.INTERRUPTED]


def test_a_claimer_whose_identity_cannot_be_read_is_not_gone(monkeypatch):
    job = _deploy_job()
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    job_claim.mark(job["id"])
    monkeypatch.setattr("harness.proc_identity.same", lambda rec: None)
    assert job_claim.starting(job["id"])
    job_claim.path(job["id"]).write_text("{not json", encoding="utf-8")
    assert job_claim.starting(job["id"])
    assert deploy.settle() == [] and wq.get(job["id"])["state"] == wq.RUNNING
