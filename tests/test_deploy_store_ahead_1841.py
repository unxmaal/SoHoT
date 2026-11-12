"""A switch that dies after the migration with no restart left ends store_ahead, with the repair what was verified allows. #1841."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from test_deploy_1506 import (BASH, _deploys, _schema, _tables, alerts, posix,  # noqa: F401 - fixtures
                              world)
from test_deploy_resume_1753 import LATER, _die_at, _handed, _worker

from harness import deploy, deploy_repair, deploy_switch, store_ahead
from harness import deploy_state as ds
from harness import memory_store as ms
from harness import workqueue as wq

DEAD = staticmethod(lambda pid: False)


def _spent(path, **more):
    rec = deploy_switch.load(path)
    rec.update(resumed=deploy.RESUMES, **more)
    deploy_switch.save(path, rec)
    return rec


def _old_worker_settles(**kw):
    """The worker of the linked release settles: its code speaks the schema before the migration."""
    return deploy.settle(now=time.time() + LATER, alive=lambda pid: False, **kw)


def _stranded(world, stage=ds.SWITCHING, files=None):
    job, path = _handed(world, files)
    _die_at(path, stage)
    _spent(path)
    return job, path


@pytest.mark.sqlite_store
@posix
def test_a_switch_killed_after_the_migration_with_no_restart_left_ends_store_ahead_not_unsettled(world, alerts):
    job, path = _stranded(world)
    got = _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec.get("outcome") == ds.STORE_AHEAD, rec.get("detail") or f"settled {got}, record {rec.get('stage')}"
    assert rec["repair"] == deploy_repair.RESTORE
    assert f"soh deploy repair {rec['id']}" in rec["detail"] and rec["backup"] in rec["detail"]
    assert f"schema {ms.SCHEMA_VERSION + 1}" in rec["detail"] and f"speaks {ms.SCHEMA_VERSION}" in rec["detail"]
    assert [g["outcome"] for g in got] == [ds.STORE_AHEAD]
    assert _schema() == ms.SCHEMA_VERSION + 1, "settle repaired on its own after the switch's restarts were spent"
    assert wq.paused(), "the queue was let go onto a store its code cannot read"
    assert len(alerts) == 1 and f"soh deploy repair {rec['id']}" in alerts[0]


@pytest.mark.sqlite_store
@posix
def test_the_worker_that_speaks_the_store_closes_the_row_store_ahead_not_interrupted(world, alerts):
    job, path = _stranded(world)
    _worker(deploy.settle, now=time.time() + LATER, alive=lambda pid: False)
    d = _worker(_deploys)[0]
    assert d["outcome"] == ds.STORE_AHEAD, d["detail"]
    assert "soh deploy repair" in d["detail"]
    assert _worker(wq.get, job["id"])["state"] == wq.FAILED
    assert wq.paused()


@pytest.mark.sqlite_store
@posix
def test_a_switch_that_cannot_be_started_again_after_the_migration_ends_store_ahead(world, alerts, monkeypatch):
    job, path = _handed(world, {"fail-smoke-live": ""})
    _die_at(path, ds.FLIPPED_BACK)

    def refuse(path, release):
        raise deploy.DeployError("launchctl bootstrap: refused")
    monkeypatch.setattr(deploy, "respawn", refuse, raising=False)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec.get("outcome") == ds.STORE_AHEAD, rec.get("detail")
    assert "starting it again failed" in rec["detail"] and "refused" in rec["detail"]


@pytest.mark.sqlite_store
@posix
def test_the_old_worker_resumes_a_switch_with_a_restart_left_without_opening_the_store(world, alerts, monkeypatch):
    job, path = _handed(world)
    _die_at(path, ds.SWITCHING)
    started = []

    def inline(path, release):
        started.append(path)
        deploy_switch.switch(path)
        return "inline"
    monkeypatch.setattr(deploy, "respawn", inline, raising=False)
    _old_worker_settles()
    assert started == [path], "the old release's worker could not settle a deploy whose store is ahead of it"
    rec = deploy_switch.load(path)
    assert rec["outcome"] == ds.ROLLED_BACK and _schema() == ms.SCHEMA_VERSION
    _old_worker_settles()
    assert _deploys()[0]["outcome"] == ds.ROLLED_BACK


@pytest.mark.sqlite_store
@posix
def test_no_migration_or_a_restored_store_stays_interrupted(world, alerts):
    job, path = _handed(world, migrate=False)
    _die_at(path, ds.FLIPPED)
    _spent(path)
    deploy.settle(now=time.time() + LATER, alive=lambda pid: False)
    assert _deploys()[0]["outcome"] == ds.INTERRUPTED


@pytest.mark.sqlite_store
@posix
def test_a_switch_dead_after_it_verified_is_not_store_ahead(world, alerts):
    job, path = _stranded(world, ds.VERIFIED)
    _worker(deploy.settle, now=time.time() + LATER, alive=lambda pid: False)
    assert _worker(_deploys)[0]["outcome"] == ds.INTERRUPTED


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("unverified", ["missing", "another schema"])
def test_a_backup_that_does_not_verify_flips_forward_to_the_release_that_speaks_the_store(world, alerts, unverified):
    job, path = _stranded(world)
    rec = deploy_switch.load(path)
    if unverified == "missing":
        Path(rec["backup"]).unlink()
    else:
        shutil.copyfile(rec["db"], rec["backup"])
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec["repair"] == deploy_repair.FORWARD, rec["detail"]
    assert rec["release"] in rec["detail"] and "soh deploy repair" in rec["detail"]


@pytest.mark.sqlite_store
@posix
def test_with_neither_the_backup_nor_the_release_verified_the_owner_is_told_no_repair_runs(world, alerts):
    job, path = _stranded(world)
    rec = deploy_switch.load(path)
    Path(rec["backup"]).unlink()
    (Path(rec["release"]) / "harness" / "memory_store" / "schema.py").write_text("SCHEMA_VERSION = 1\n",
                                                                                encoding="utf-8")
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec["repair"] == deploy_repair.OWNER, rec["detail"]
    got = deploy_repair.repair(rec["id"])
    assert not got["ok"] and _schema() == ms.SCHEMA_VERSION + 1 and wq.paused()


@pytest.mark.sqlite_store
@posix
def test_the_restore_repair_puts_back_the_store_and_the_previous_units_and_lets_the_queue_go(world, alerts):
    job, path = _stranded(world, ds.FLIPPED)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec["repair"] == deploy_repair.RESTORE
    assert [p["deploy"] for p in deploy_repair.pending()] == [rec["id"]]
    assert "soh deploy repair" in deploy.blocked(running=lambda home: [])
    world["log"].write_text("", encoding="utf-8")
    got = deploy_repair.repair(rec["id"])
    assert got["ok"], got["detail"]
    assert world["link"].resolve() == Path(rec["previous"]).resolve()
    assert _schema() == ms.SCHEMA_VERSION and "planted_by_migration" not in _tables()
    steps = world["log"].read_text(encoding="utf-8")
    previous = Path(rec["previous"]).resolve().name
    assert f"reinstall {previous}" in steps and f"smoke {previous}" in steps, steps
    assert not wq.paused()
    assert deploy_repair.pending() == [] and deploy.blocked(running=lambda home: []) == ""
    assert deploy_repair.repair(rec["id"])["ok"] is False, "a repaired deploy was repaired twice"
    _old_worker_settles()
    d = _deploys()[0]
    assert d["outcome"] == ds.STORE_AHEAD and wq.get(job["id"])["state"] == wq.FAILED


@pytest.mark.sqlite_store
@posix
def test_the_forward_repair_links_the_release_reinstalls_and_verifies_it(world, alerts):
    job, path = _stranded(world)
    Path(deploy_switch.load(path)["backup"]).unlink()
    _old_worker_settles()
    rec = deploy_switch.load(path)
    world["log"].write_text("", encoding="utf-8")
    got = deploy_repair.repair(rec["id"])
    assert got["ok"], got["detail"]
    assert world["link"].resolve() == Path(rec["release"]).resolve()
    assert _schema() == ms.SCHEMA_VERSION + 1
    steps = world["log"].read_text(encoding="utf-8")
    release = Path(rec["release"]).resolve().name
    assert f"reinstall {release}" in steps and f"smoke {release}" in steps, steps
    assert not wq.paused()


@pytest.mark.sqlite_store
@posix
def test_a_repair_whose_step_fails_keeps_the_queue_paused_and_stays_pending(world, alerts):
    job, path = _stranded(world)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    rec["rollback_install"] = [BASH, "-c", "exit 3"]
    deploy_switch.save(path, rec)
    got = deploy_repair.repair(rec["id"])
    assert not got["ok"] and "exited rc 3" in got["detail"]
    assert wq.paused() and [p["deploy"] for p in deploy_repair.pending()] == [rec["id"]]


@pytest.mark.sqlite_store
@posix
@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/deploy_state.py:MOVES:store_ahead")
def test_morning_and_every_verb_on_the_old_release_say_the_repair(world, alerts):
    job, path = _stranded(world)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    from harness import morning
    lines = deploy_repair.lines(morning.deploy_repairs())
    assert len(lines) == 1 and f"soh deploy repair {rec['id']}" in lines[0] and "restore" in lines[0]
    r = {"deploy_repairs": morning.deploy_repairs(), "sweep": {"loop": None}, "deploy": {}, "stale": [], "ci": {},
         "watchdog": [], "incidents": []}
    assert lines[0] in morning.needs(r)
    root = Path(rec["previous"]).resolve()
    kind = store_ahead.verdict(root=root, link=world["link"], running=True)
    assert kind == store_ahead.REPAIR
    said = store_ahead.line(kind, RuntimeError("discovery.db is schema 9, this code speaks 8."), root)
    assert f"soh deploy repair {rec['id']}" in said and kind not in store_ahead.QUIET


@pytest.mark.sqlite_store
@posix
def test_a_late_switch_on_a_store_ahead_record_is_refused(world, alerts):
    job, path = _stranded(world)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    deploy_switch.save(path, {**rec, "resume": rec["stage"]})
    with pytest.raises(ds.IllegalMove):
        deploy_switch.switch(path)


@pytest.mark.sqlite_store
@posix
def test_soh_deploy_repair_lists_then_does_the_repair_without_opening_the_store(world, alerts, capsys):
    from harness import cli
    job, path = _stranded(world)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert cli.main(["deploy", "repair"]) == 0
    assert f"soh deploy repair {rec['id']}" in capsys.readouterr().out
    assert cli.main(["deploy", "repair", "x"]) == 1
    assert cli.main(["deploy", "repair", str(rec["id"])]) == 0, capsys.readouterr()
    assert f"deploy {rec['id']} repaired (restore)" in capsys.readouterr().out
    assert _schema() == ms.SCHEMA_VERSION and not wq.paused()
    assert cli.main(["deploy", "repair", str(rec["id"])]) == 1


@pytest.mark.sqlite_store
@posix
@pytest.mark.gauntlet("a-deploy-runs-two-releases-at-once", site="harness/deploy.py:_speaks:one-sided")
def test_the_store_pass_ends_store_ahead_when_the_resume_cannot_start(world, alerts, monkeypatch):
    job, path = _handed(world)
    _die_at(path, ds.SWITCHING)

    tried = []

    def refuse(path, release):
        tried.append(path)
        raise OSError("no launchd here")
    monkeypatch.setattr(deploy, "respawn", refuse, raising=False)
    assert _worker(deploy.recover, time.time() + LATER, lambda pid: False, refuse) == [] and tried == [], \
        "a worker that can open the store took the resume away from the store pass"
    _worker(deploy.settle, now=time.time() + LATER, alive=lambda pid: False)
    assert len(tried) == 1
    d = _worker(_deploys)[0]
    assert d["outcome"] == ds.STORE_AHEAD and "no launchd here" in d["detail"], d["detail"]
    assert _worker(wq.get, job["id"])["state"] == wq.FAILED and wq.paused()


class Died(BaseException):
    """The repair process killed mid-way: nothing after the step runs."""


@pytest.mark.sqlite_store
@posix
@pytest.mark.gauntlet("two-durable-writes-with-no-repair-for-the-gap", site="harness/deploy_repair.py:repair")
def test_a_repair_killed_after_the_restore_is_finished_by_running_it_again(world, alerts):
    job, path = _stranded(world)
    _old_worker_settles()
    rec = deploy_switch.load(path)

    def killed(*a, **kw):
        raise Died("after the restore, before the reinstall")
    with pytest.MonkeyPatch.context() as mp, pytest.raises(Died):
        mp.setattr(deploy_switch, "_step", killed)
        deploy_repair.repair(rec["id"])
    assert _schema() == ms.SCHEMA_VERSION and wq.paused() and deploy_repair.pending()
    got = deploy_repair.repair(rec["id"])
    assert got["ok"] and got["how"] == deploy_repair.RESTORE, got["detail"]
    assert world["link"].resolve() == Path(rec["previous"]).resolve() and not wq.paused()
    assert deploy_repair.pending() == []


@pytest.mark.sqlite_store
@posix
@pytest.mark.gauntlet("a-deploy-runs-two-releases-at-once", site="harness/deploy_repair.py:schemas:one-sided")
def test_a_store_already_back_at_the_previous_schema_is_not_store_ahead(world, alerts):
    job, path = _stranded(world)
    rec = deploy_switch.load(path)
    deploy_switch.restore(Path(rec["backup"]), Path(rec["db"]))
    assert deploy_repair.schemas(rec) is None
    deploy.settle(now=time.time() + LATER, alive=lambda pid: False)
    assert _deploys()[0]["outcome"] == ds.INTERRUPTED


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value",
                      site="harness/deploy_repair.py:_backup_unverified:chooser")
@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/deploy_repair.py:_backup_unverified:verify")
def test_a_postgres_dump_that_does_not_read_does_not_verify(monkeypatch, tmp_path):
    from harness import store, store_service
    dump = tmp_path / "pre.dump"
    dump.write_bytes(b"not a dump")
    monkeypatch.setattr(store, "backend", lambda: store.POSTGRES)

    def unreadable(path, **kw):
        raise RuntimeError("pg_restore -l: input file does not appear to be a valid archive")
    monkeypatch.setattr(store_service, "verify", unreadable)
    assert "valid archive" in deploy_repair._backup_unverified({"backup": str(dump)}, 99)
    monkeypatch.setattr(store_service, "verify", lambda path, **kw: None)
    assert deploy_repair._backup_unverified({"backup": str(dump)}, 99) == ""
