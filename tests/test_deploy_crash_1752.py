"""A deploy that dies at any durable step before its switch is undone by settle: store schema and queue pause. #1752."""
from __future__ import annotations

import time

import pytest
from test_deploy_1506 import _claim, _deploys, _queue, _schema, _tables, alerts, posix, world  # noqa: F401 - fixtures
from test_deploy_quiesce_1795 import NEXT, _steps

from harness import deploy, deploy_switch
from harness import memory_store as ms
from harness import workqueue as wq

LATER = deploy.HANDOFF_GRACE_S + 1


class Died(BaseException):
    """The deploy job's process killed right after a step: nothing after it runs, no cleanup."""


def _after(monkeypatch, owner, name, when):
    """Kill the run right after owner.name returns, the first time when(*args) holds."""
    real, done = getattr(owner, name), []

    def wrapped(*args, **kw):
        got = real(*args, **kw)
        if not done and when(*args):
            done.append(True)
            raise Died(name)
        return got
    monkeypatch.setattr(owner, name, wrapped)


def _taking(step):
    return lambda path, rec: rec.get("taking") == step and not rec.get("outcome")


def _inject(point, monkeypatch, steps):
    if point == "record_pause":
        _after(monkeypatch, deploy_switch, "save", _taking(deploy.PAUSE))
    elif point == "pause":
        _after(monkeypatch, wq, "pause", lambda *a: True)
    elif point == "backup":
        _after(monkeypatch, deploy, "backup", lambda *a: True)
    elif point == "migrate":
        _after(monkeypatch, deploy, "_run", lambda argv, *a: argv == steps.migrate)
    elif point == "record":
        _after(monkeypatch, deploy_switch, "save", _taking(deploy.RECORD))


def _spawn(point):
    def spawn(path, release):
        if point == "row":
            raise Died("spawn")
        pytest.fail("the switch was spawned")
    return spawn


def _die(world, point, owner_paused=False):
    job = _claim(_queue(world, NEXT))
    if owner_paused:
        wq.pause("owner")
    steps = _steps(world)
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Died):
        _inject(point, mp, steps)
        deploy.run(job["output"], job["id"], link=world["link"], steps=steps, spawn=_spawn(point))
    return job


POINTS = ["record_pause", "pause", "backup", "migrate", "record", "row"]
MIGRATED = {"migrate", "record", "row"}


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("owner_paused", [False, True])
@pytest.mark.parametrize("point", POINTS)
def test_a_death_after_each_step_leaves_the_store_on_the_linked_schema_and_only_an_owner_pause(
        world, monkeypatch, alerts, point, owner_paused):
    job = _die(world, point, owner_paused)
    assert wq.paused() == (owner_paused or point != "record_pause"), "the deploy's pause outlived it"
    if point in MIGRATED:
        assert _schema() == ms.SCHEMA_VERSION + 1, "the store was left ahead of the linked release"
    got = deploy.settle(now=time.time() + LATER, alive=lambda pid: False)
    assert [g["outcome"] for g in got] == [deploy.INTERRUPTED]
    assert _schema() == wq.code_schema(world["link"].resolve()) == ms.SCHEMA_VERSION
    assert "planted_by_migration" not in _tables()
    assert wq.paused() == owner_paused
    d = _deploys()[0]
    assert d["outcome"] == deploy.INTERRUPTED
    assert ("restored from" in d["detail"]) == (point in MIGRATED), d["detail"]
    assert wq.get(job["id"])["state"] == wq.FAILED
    assert len(alerts) == 1
    assert deploy.settle(now=time.time() + LATER, alive=lambda pid: False) == [] and len(alerts) == 1


@pytest.mark.sqlite_store
@posix
def test_settle_waits_while_the_deploy_job_still_runs(world, monkeypatch, alerts):
    _die(world, "backup")
    assert deploy.settle(now=time.time() + LATER, alive=lambda pid: True) == []
    assert wq.paused() and not alerts and _deploys()[0]["outcome"] == ""


@pytest.mark.sqlite_store
@posix
def test_a_pause_its_owner_set_after_the_deploy_is_not_lifted(world, monkeypatch, alerts):
    _die(world, "backup")
    wq.pause("owner, after the deploy")
    deploy.settle(alive=lambda pid: False)
    assert wq.paused()
    assert "its owner paused it after the deploy did" in _deploys()[0]["detail"]


@pytest.mark.sqlite_store
@posix
def test_a_store_the_linked_release_reads_is_recorded_not_restored(world, monkeypatch, alerts):
    _die(world, "migrate")
    monkeypatch.setattr(wq, "code_schema", lambda cwd: ms.SCHEMA_VERSION + 1)
    got = deploy.recover(alive=lambda pid: False)
    assert "reads the store at schema" in got[0]["detail"] and "restored from" not in got[0]["detail"]
    assert _schema() == ms.SCHEMA_VERSION + 1 and "planted_by_migration" in _tables()
    assert not wq.paused()


@pytest.mark.sqlite_store
@posix
def test_a_failed_restore_keeps_the_queue_paused_and_says_so(world, monkeypatch, alerts):
    _die(world, "migrate")

    def gone(backup, db):
        raise OSError("backup gone")
    monkeypatch.setattr(deploy_switch, "restore", gone)
    got = deploy.recover(alive=lambda pid: False)
    assert "FAILED (OSError: backup gone)" in got[0]["detail"]
    assert wq.paused() and _schema() == ms.SCHEMA_VERSION + 1
    assert len(alerts) == 1 and deploy.recover(alive=lambda pid: False) == [], "a failed restore is not retried"


@pytest.mark.sqlite_store
@posix
def test_a_late_switch_refuses_a_record_settle_interrupted(world, monkeypatch, alerts):
    _die(world, "row")
    deploy.settle(now=time.time() + LATER, alive=lambda pid: False)
    path = deploy.record_path(_deploys()[0]["id"])
    with pytest.raises(deploy.ds.IllegalMove):
        deploy_switch.switch(path)
    assert deploy_switch.load(path)["outcome"] == deploy.INTERRUPTED
