"""A switch that dies between its durable writes is resumed from its stage (#1753); a reused pid never reads as the switch (#1773)."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_deploy_1506 import (BASH, _claim, _deploys, _queue, _schema, _tables, alerts, posix,  # noqa: F401 - fixtures
                              world)
from test_deploy_quiesce_1795 import NEXT

from harness import deploy, deploy_switch, proc_identity
from harness import deploy_state as ds
from harness import memory_store as ms
from harness.memory_store import connection, migrations
from harness import workqueue as wq

LATER = deploy.HANDOFF_GRACE_S + 1
FORWARD = [ds.SWITCHING, ds.FLIPPED, ds.INSTALLED]
BACK = [ds.ROLLING_BACK, ds.FLIPPED_BACK, ds.RESTORED, ds.ROLLBACK_INSTALLED, ds.ROLLBACK_VERIFIED]


class Died(BaseException):
    """The switch process killed right after a stage was saved: nothing after it runs."""


def _handed(world, files=None, migrate=True):
    """A deploy handed off to a switch that has not started; (job, record path)."""
    job = _claim(_queue(world, {**(NEXT if migrate else {"f": "two\n"}), **(files or {})}))
    handed = []
    rc = deploy.run(job["output"], job["id"], link=world["link"], steps=world["steps"],
                    spawn=lambda path, release: handed.append(path) or "launchd")
    assert rc == deploy.HANDED_OFF and wq.paused()
    assert _schema() == ms.SCHEMA_VERSION + migrate
    return job, Path(handed[0])


def _worker(fn, *args, **kw):
    """fn as the worker of whichever release serves runs it: its code speaks the schema the store is at."""
    with pytest.MonkeyPatch.context() as mp:
        for reader in (migrations, connection):
            mp.setattr(reader, "SCHEMA_VERSION", _schema())
        return fn(*args, **kw)


def _die_at(path, stage):
    real, done = deploy_switch.save, []

    def save(p, rec):
        real(p, rec)
        if not done and rec.get("stage") == stage and not rec.get("outcome"):
            done.append(True)
            raise Died(stage)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Died):
        mp.setattr(deploy_switch, "save", save)
        deploy_switch.switch(path)
    rec = deploy_switch.load(path)
    assert (rec["stage"], rec.get("outcome", "")) == (stage, "")
    return rec


def _resume_inline(monkeypatch):
    started = []

    def inline(path, release):
        started.append(path)
        deploy_switch.switch(path)
        return "inline"
    monkeypatch.setattr(deploy, "respawn", inline, raising=False)
    return started


def _settled(alive):
    _worker(deploy.settle, now=time.time() + LATER, alive=alive)
    return _worker(deploy.settle, now=time.time() + LATER, alive=alive)


def _rolled_back(world, job, stage):
    previous = Path(deploy_switch.load(next(deploy.records_dir().glob("*.json")))["previous"])
    assert world["link"].resolve() == previous.resolve(), "the link was left on the new release"
    assert _schema() == ms.SCHEMA_VERSION and "planted_by_migration" not in _tables(), "the store was left migrated"
    d = _deploys()[0]
    assert d["outcome"] == deploy.ROLLED_BACK, d["detail"]
    assert f"died at {stage}" in d["detail"]
    assert not wq.paused()
    assert wq.get(job["id"])["state"] == wq.FAILED


@pytest.mark.sqlite_store
@posix
def test_a_switch_killed_between_the_flip_and_the_install_is_rolled_back(world, monkeypatch, alerts):
    job, path = _handed(world)
    rec = deploy_switch.load(path)
    rec["install"] = [BASH, "-c", "kill -KILL $PPID; sleep 5"]
    deploy_switch.save(path, rec)
    got = subprocess.run(deploy.switch_argv(path), capture_output=True, text=True, timeout=120)
    assert got.returncode == -9, got.stderr
    rec = deploy_switch.load(path)
    assert (rec["stage"], rec.get("outcome", "")) == (ds.FLIPPED, "")
    assert world["link"].resolve() == Path(rec["release"]).resolve()
    started = _resume_inline(monkeypatch)
    _settled(wq.alive)
    assert started == [path]
    _rolled_back(world, job, ds.FLIPPED)
    assert "reinstall" in world["log"].read_text(encoding="utf-8")


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("stage", FORWARD + [ds.VERIFIED])
def test_a_switch_dead_on_the_way_forward_is_resumed_from_its_stage(world, monkeypatch, alerts, stage):
    job, path = _handed(world)
    _die_at(path, stage)
    _resume_inline(monkeypatch)
    _settled(lambda pid: False)
    if stage == ds.VERIFIED:
        d = _worker(_deploys)[0]
        assert d["outcome"] == deploy.DEPLOYED, d["detail"]
        assert world["link"].resolve() == Path(d["release"]).resolve()
        assert _schema() == ms.SCHEMA_VERSION + 1 and not wq.paused()
        assert _worker(wq.get, job["id"])["state"] == wq.DONE
    else:
        _rolled_back(world, job, stage)


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("stage", BACK)
def test_a_switch_dead_mid_rollback_finishes_the_rollback(world, monkeypatch, alerts, stage):
    job, path = _handed(world, {"fail-smoke-live": ""})
    _die_at(path, stage)
    _resume_inline(monkeypatch)
    _settled(lambda pid: False)
    _rolled_back(world, job, stage)
    assert "smoke" in _deploys()[0]["detail"], "the resumed rollback forgot why it rolled back"


@pytest.mark.sqlite_store
@posix
def test_a_switch_dead_after_a_failed_restore_ends_failed_forward_on_its_own_release(world, monkeypatch, alerts):
    job, path = _handed(world, {"fail-smoke-live": ""})

    def gone(backup, db):
        raise OSError("backup gone")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(deploy_switch, "restore", gone)
        rec = _die_at(path, ds.RESTORE_FAILED)
    deploy_switch.flip(Path(rec["link"]), Path(rec["previous"]))
    _resume_inline(monkeypatch)
    _settled(lambda pid: False)
    assert world["link"].resolve() == Path(rec["release"]).resolve(), "the newer store is left to the older release"
    d = _worker(_deploys)[0]
    assert d["outcome"] == ds.FAILED_FORWARD and "backup gone" in d["detail"], d["detail"]
    assert _schema() == ms.SCHEMA_VERSION + 1


@pytest.mark.sqlite_store
@posix
def test_a_resumed_switch_that_dies_again_is_interrupted_not_resumed_forever(world, monkeypatch, alerts):
    job, path = _handed(world, migrate=False)
    _die_at(path, ds.FLIPPED)
    started = []
    monkeypatch.setattr(deploy, "respawn", lambda path, release: started.append(path) or "launchd", raising=False)
    assert deploy.settle(now=time.time() + LATER, alive=lambda pid: False) == []
    assert deploy.settle(now=time.time() + LATER + 1, alive=lambda pid: False) == [], "the resumed switch got no grace"
    deploy.settle(now=time.time() + 2 * LATER, alive=lambda pid: False)
    assert len(started) == 1
    d = _deploys()[0]
    assert d["outcome"] == deploy.INTERRUPTED and "without an outcome" in d["detail"]
    assert wq.get(job["id"])["state"] == wq.FAILED and len(alerts) == 1


@pytest.mark.sqlite_store
@posix
def test_a_switch_that_cannot_be_started_again_is_interrupted_and_said(world, alerts):
    job, path = _handed(world, migrate=False)
    _die_at(path, ds.FLIPPED)
    deploy.settle(now=time.time() + LATER, alive=lambda pid: False)
    d = _deploys()[0]
    assert d["outcome"] == deploy.INTERRUPTED and "starting it again failed" in d["detail"]
    assert wq.get(job["id"])["state"] == wq.FAILED and len(alerts) == 1


@pytest.mark.sqlite_store
@posix
def test_a_record_settle_did_not_hand_back_is_refused(world):
    job, path = _handed(world, migrate=False)
    _die_at(path, ds.FLIPPED)
    rec = deploy_switch.load(path)
    deploy_switch.save(path, {**rec, "resume": ds.INSTALLED})
    with pytest.raises(ds.IllegalMove):
        deploy_switch.switch(path)


# --- #1773: the switch's pid after a reboot -------------------------------------------------------------------------


@pytest.fixture
def stranger():
    """A live process that started after the switch's record: what a launchd service holds after a reboot."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        yield p
    finally:
        p.kill()
        p.wait()


def _switch_died_before_boot(world, stranger, started=None, **ident):
    job, path = _handed(world, migrate=False)
    _die_at(path, ds.FLIPPED)
    rec = deploy_switch.load(path)
    rec.pop("identity", None)
    rec.update(pid=stranger.pid, switch_started=started or time.time() - 3600, resumed=99, **ident)
    deploy_switch.save(path, rec)
    return job


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("written_by", ["an older switch, pid only", "this switch, pid and identity"])
def test_a_pid_reused_after_a_reboot_does_not_keep_the_deploy_running(world, alerts, stranger, written_by):
    # With an identity the record's start time is after the stranger's, so only the identity can tell them apart.
    ident = {} if written_by.startswith("an older") else {
        "started": time.time(),
        "identity": {"pid": stranger.pid, "pgid": os.getpgid(stranger.pid), "started": "1.000000"}}
    job = _switch_died_before_boot(world, stranger, **ident)
    got = deploy.settle(now=time.time() + LATER)
    assert [g["outcome"] for g in got] == [deploy.INTERRUPTED], "the deploy reads as running forever"
    assert wq.get(job["id"])["state"] == wq.FAILED
    assert not wq.paused(), "the queue pause the deploy took was never lifted"


@pytest.mark.sqlite_store
@posix
def test_the_switch_itself_still_reads_as_running(world, alerts, stranger):
    job = _switch_died_before_boot(world, stranger, identity=proc_identity.identity(stranger.pid),
                                   started=time.time())
    assert deploy.settle(now=time.time() + LATER) == []
    assert wq.get(job["id"])["state"] == wq.RUNNING and wq.paused()


@pytest.mark.sqlite_store
@posix
def test_a_reused_pid_never_holds_back_recovery_of_a_job_that_died(world, alerts, stranger):
    job = _claim(_queue(world, NEXT))
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Died):
        real = deploy.backup

        def backup(*a):
            real(*a)
            raise Died("backup")
        mp.setattr(deploy, "backup", backup)
        deploy.run(job["output"], job["id"], link=world["link"], steps=world["steps"],
                   spawn=lambda *a: pytest.fail("the switch was spawned"))
    path = deploy.record_path(_deploys()[0]["id"])
    rec = deploy_switch.load(path)
    rec.update(run_pid=stranger.pid,
               run_identity={"pid": stranger.pid, "pgid": os.getpgid(stranger.pid), "started": "1.000000"})
    deploy_switch.save(path, rec)
    got = deploy.recover()
    assert [g["outcome"] for g in got] == [deploy.INTERRUPTED]
    assert not wq.paused()


@posix
def test_began_is_when_the_process_started():
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        got = proc_identity.began(p.pid)
        if got is None:
            pytest.skip("this OS keeps no start time")
        assert t0 - 2 <= got <= time.time() + 2
        assert proc_identity.began(os.getpid()) <= t0
    finally:
        p.kill()
        p.wait()


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/proc_identity.py:began:except")
def test_an_unreadable_boot_time_cannot_say_and_the_pid_keeps_its_deploy(monkeypatch):
    def unread():
        raise OSError("no /proc/stat")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(proc_identity, "_proc", lambda pid: ("12345", False))
    monkeypatch.setattr(proc_identity, "_boot_epoch", unread)
    assert proc_identity.began(os.getpid()) is None
    assert deploy._is(os.getpid(), None, time.time() - 3600, lambda pid: True), "cannot say read as another process"


def test_a_scratch_home_never_starts_the_machines_deploy_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(deploy, "spawn_switch", lambda *a: pytest.fail("a scratch home reached launchd"))
    with pytest.raises(deploy.DeployError, match="not the live home"):
        deploy.respawn(tmp_path / "1.json", tmp_path)
