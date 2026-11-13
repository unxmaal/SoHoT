"""A deploy pauses the queue and waits for the jobs running here before it migrates the store, within a bound. #1795, #1787."""
from __future__ import annotations

import dataclasses
import subprocess
import sys
import threading
import time
import types

import pytest
from test_deploy_1506 import (_claim, _deploys, _Done, _git, _inline, _queue, _schema, _tables, alerts,  # noqa: F401 - fixtures
                              posix, world)

from harness import deploy, deploy_switch, paths
from harness import memory_store as ms
from harness import workqueue as wq
from harness import job_procs, queue_pause

MIGRATE = """import os, sqlite3, sys
with open(os.environ["DEPLOY_LOG"], "a") as log:
    log.write(f"migrate paused={os.path.exists(sys.argv[3])}\\n")
c = sqlite3.connect(sys.argv[1])
c.execute("CREATE TABLE planted_by_migration (x)")
c.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (sys.argv[2],))
c.commit()
"""
NEXT = {"harness/memory_store/schema.py": f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n"}


def _steps(world):
    return dataclasses.replace(world["steps"], migrate=[sys.executable, "-c", MIGRATE, str(ms.db_path()),
                                                        str(ms.SCHEMA_VERSION + 1), str(queue_pause._pause_flag())])


def _old_job():
    """A job of the serving release running here, its process alive and leading its own group."""
    job = wq.add([sys.executable, "-c", "pass"], title="old release job", cwd=str(paths.home()))
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    proc = wq.spawn_group([sys.executable, "-c", "import time; time.sleep(120)"], None, subprocess.DEVNULL, None)
    job_procs._pid_file(job["id"]).write_text(str(proc.pid), encoding="utf-8")
    return job, proc


def _end(proc) -> None:
    proc.kill()
    proc.wait(timeout=10)


def _run(job, world, sleep):
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        return _Done(deploy.run(argv[-1], job["id"], link=world["link"], steps=_steps(world), spawn=_inline,
                                sleep=sleep))
    return wq.run_one(job, popen=popen)


@pytest.mark.sqlite_store
@posix
def test_a_deploy_does_not_migrate_until_the_old_release_job_running_here_has_ended(world):
    job = _queue(world, NEXT)
    other, proc = _old_job()
    seen = []

    def sleep(s):
        seen.append((wq.paused(), _schema(), "planted_by_migration" in _tables()))
        if len(seen) == 2:
            _end(proc)

    handed = []
    _claim(job)
    try:
        # This test's own code speaks the old schema, as the old worker does, so the switch is not run here.
        rc = deploy.run(job["output"], job["id"], link=world["link"], steps=_steps(world),
                        spawn=lambda path, release: handed.append(path) or "planted", sleep=sleep)
    finally:
        if proc.poll() is None:
            _end(proc)
    assert rc == deploy.HANDED_OFF
    assert seen[:2] == [(True, ms.SCHEMA_VERSION, False)] * 2, "paused, and not migrated while the job ran"
    assert _schema() == ms.SCHEMA_VERSION + 1 and "planted_by_migration" in _tables()
    assert "migrate paused=True" in world["log"].read_text(encoding="utf-8")
    rec = deploy_switch.load(handed[0])
    assert rec["migrated"] and rec["queue_was_paused"] is False, "the switch lifts the pause the deploy set"


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("owner_paused", [False, True])
def test_a_job_that_never_ends_fails_the_deploy_not_quiesced_with_the_store_unmigrated(world, monkeypatch, alerts,
                                                                                      owner_paused):
    monkeypatch.setattr(deploy, "QUIESCE_TIMEOUT_S", 0.3)
    job = _queue(world, NEXT)
    if owner_paused:
        wq.pause("owner")
    other, proc = _old_job()
    try:
        ran = _run(job, world, lambda s: time.sleep(min(s, 0.05)))
    finally:
        _end(proc)
    assert ran["state"] == wq.FAILED and ran["rc"] == 1
    d = _deploys()[0]
    assert d["outcome"] == deploy.FAILED and d["detail"].startswith(f"{deploy.NOT_QUIESCED}: job {other['id']} ")
    assert f"the store stays at schema {ms.SCHEMA_VERSION}" in d["detail"]
    assert d["backup"] == "" and _schema() == ms.SCHEMA_VERSION and "planted_by_migration" not in _tables()
    assert _git(world["link"], "rev-parse", "HEAD") == world["first"]
    assert deploy_switch.load(deploy.record_path(d["id"]))["outcome"] == deploy.FAILED
    steps = world["log"].read_text(encoding="utf-8")
    assert "migrate" not in steps and "reinstall" not in steps
    assert wq.paused() == owner_paused, "the deploy lifts only the pause it set"


@pytest.mark.sqlite_store
@posix
def test_a_deploy_with_no_migration_does_not_wait_on_a_running_job(world):
    job = _queue(world, {"f": "two\n"})
    other, proc = _old_job()
    try:
        _run(job, world, lambda s: pytest.fail("a deploy that migrates nothing waited"))
    finally:
        _end(proc)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.DEPLOYED]
    assert not wq.paused()


def test_the_runner_reads_no_store_while_a_deploy_runs_in_it(monkeypatch):
    live = threading.Event()
    calls = []
    real = wq._startable
    monkeypatch.setattr(queue_pause, "deploy_turn", lambda now: calls.append(("turn", live.is_set())))
    monkeypatch.setattr(wq, "_startable", lambda *a: calls.append(("start", live.is_set())) or real(*a))

    def popen(argv, **kw):
        live.set()
        time.sleep(0.5)
        live.clear()
        return types.SimpleNamespace(returncode=1)

    wq.add(["soh", "deploy", "run", "abc"], title="deploy abc", cwd=str(paths.home()), kind=deploy.KIND,
           output="abc", priority=deploy.PRIORITY)
    wq.run_pending(popen=popen, clock=time.time, watch=0.02)
    assert ("start", False) in calls
    assert not [c for c in calls if c[1]], "the runner polled the store while the deploy ran"
