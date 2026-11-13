"""A store_ahead deploy whose pre-migrate copy verifies restores it by itself, once; forward and owner repairs stay the owner's. #1879."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_deploy_1506 import (BASH, _deploys, _schema, _tables, alerts, posix,  # noqa: F401 - fixtures
                              world)
from test_deploy_resume_1753 import LATER, _worker
from test_deploy_store_ahead_1841 import _old_worker_settles, _stranded

from harness import deploy, deploy_repair, deploy_switch, paths
from harness import deploy_state as ds
from harness import memory_store as ms
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]


def _inline(started):
    """The repair process, here in process: what deploy_repair.start hands to launchd on the live home."""
    def start(deploy_id):
        started.append(deploy_id)
        deploy_repair.run_auto(deploy_id)
        return "inline"
    return start


def _counting(mp, fail=False):
    """Calls of the store restore, the step a repair cannot take twice without harm."""
    calls, real = [], deploy_switch.restore

    def restore(backup, db):
        calls.append(backup)
        if fail:
            raise OSError("disk full")
        return real(backup, db)
    mp.setattr(deploy_switch, "restore", restore)
    return calls


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("worker", ["old", "speaks the store"])
def test_a_verified_copy_is_restored_by_itself_with_no_cli_call(world, alerts, monkeypatch, worker):
    job, path = _stranded(world, ds.FLIPPED)
    calls, started = _counting(monkeypatch), []
    if worker == "old":
        _old_worker_settles(start=_inline(started))
    else:
        _worker(deploy.settle, now=time.time() + LATER, alive=lambda pid: False, start=_inline(started))
    rec = deploy_switch.load(path)
    assert started == [rec["id"]], rec.get("detail")
    assert rec["outcome"] == ds.STORE_AHEAD and rec["repaired"]["how"] == deploy_repair.RESTORE
    assert rec["auto_repair"]["state"] == deploy_repair.REPAIRED and rec["auto_repair"]["pid"] == os.getpid()
    assert world["link"].resolve() == Path(rec["previous"]).resolve()
    assert _schema() == ms.SCHEMA_VERSION and "planted_by_migration" not in _tables()
    assert len(calls) == 1 and not wq.paused()
    said = [a for a in alerts if "repaired itself" in a]
    assert len(said) == 1, alerts
    assert rec["backup"] in said[0] and rec["previous"] in said[0] and f"schema {ms.SCHEMA_VERSION}" in said[0]
    assert deploy_repair.pending() == []
    _old_worker_settles(start=_inline(started))
    assert started == [rec["id"]] and len(calls) == 1
    assert _deploys()[0]["outcome"] == ds.STORE_AHEAD and wq.get(job["id"])["state"] == wq.FAILED


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("unverified", ["missing", "another schema"])
def test_a_copy_that_does_not_verify_is_not_restored_and_the_queue_stays_paused(world, alerts, monkeypatch, unverified):
    job, path = _stranded(world)
    rec = deploy_switch.load(path)
    if unverified == "missing":
        Path(rec["backup"]).unlink()
    else:
        shutil.copyfile(rec["db"], rec["backup"])
    calls, started = _counting(monkeypatch), []
    for _ in range(2):
        _old_worker_settles(start=_inline(started))
    rec = deploy_switch.load(path)
    assert rec["outcome"] == ds.STORE_AHEAD and not rec.get("repaired") and "auto_repair" not in rec
    assert started == [] and calls == [], "a repair was attempted on a copy that does not verify"
    assert [p["deploy"] for p in deploy_repair.pending()] == [rec["id"]]
    assert wq.paused() and _schema() == ms.SCHEMA_VERSION + 1


@pytest.mark.sqlite_store
@posix
def test_a_failing_restore_step_is_attempted_exactly_once_across_settles(world, alerts, monkeypatch):
    job, path = _stranded(world, ds.FLIPPED)
    started = []
    with pytest.MonkeyPatch.context() as mp:
        calls = _counting(mp, fail=True)
        for _ in range(3):
            _old_worker_settles(start=_inline(started))
    rec = deploy_switch.load(path)
    assert len(calls) == 1 and started == [rec["id"]], f"restore taken {len(calls)} times"
    assert rec["auto_repair"]["state"] == deploy_repair.FAILED and not rec.get("repaired")
    assert wq.paused() and _schema() == ms.SCHEMA_VERSION + 1
    failed = [a for a in alerts if "did not repair itself" in a]
    assert len(failed) == 1, alerts
    assert "disk full" in failed[0] and f"soh deploy repair {rec['id']}" in failed[0]
    assert "automatic repair failed" in deploy_repair.lines(deploy_repair.pending())[0]
    assert deploy_repair.repair(rec["id"])["ok"], "the owner's repair after a failed automatic one"


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("when", ["at the strand", "after the strand"])
def test_a_forward_plan_is_never_run_automatically(world, alerts, when):
    job, path = _stranded(world)
    rec = deploy_switch.load(path)
    linked, started = world["link"].resolve(), []
    if when == "at the strand":
        Path(rec["backup"]).unlink()
        _old_worker_settles(start=_inline(started))
        assert deploy_switch.load(path)["repair"] == deploy_repair.FORWARD
    else:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(deploy_repair, "auto", lambda *a, **k: [])
            _old_worker_settles()
        assert deploy_switch.load(path)["auto_repair"]["state"] == deploy_repair.DUE
        Path(rec["backup"]).unlink()
    for _ in range(2):
        _old_worker_settles(start=_inline(started))
    rec = deploy_switch.load(path)
    assert started == [], "a forward repair ran without the owner"
    assert world["link"].resolve() == linked and _schema() == ms.SCHEMA_VERSION + 1
    assert not rec.get("repaired") and wq.paused()
    if when == "after the strand":
        assert rec["auto_repair"]["state"] == deploy_repair.FAILED and "not attempted" in rec["auto_repair"]["why"]
    rec["auto_repair"] = {"state": deploy_repair.STARTED, "at": time.time()}
    deploy_switch.save(path, rec)
    assert deploy_repair.run_auto(rec["id"]) == 1, "the repair process ran a forward plan"
    assert world["link"].resolve() == linked and not deploy_switch.load(path).get("repaired")


@pytest.mark.sqlite_store
@posix
def test_a_repair_process_that_dies_ends_failed_once_and_is_not_started_again(world, alerts):
    job, path = _stranded(world, ds.FLIPPED)
    started = []
    _old_worker_settles(start=lambda deploy_id: started.append(deploy_id) or "launchd")
    rec = deploy_switch.load(path)
    assert rec["auto_repair"]["state"] == deploy_repair.STARTED
    assert deploy_repair.repair(rec["id"])["ok"] is False, "the owner's repair ran beside the automatic one"
    deploy.settle(now=rec["auto_repair"]["at"] + 1, alive=lambda pid: False, start=lambda i: started.append(i))
    assert deploy_switch.load(path)["auto_repair"]["state"] == deploy_repair.STARTED, "ended inside its grace"
    rec["auto_repair"].update(pid=os.getpid(), identity={"pid": os.getpid()})
    deploy_switch.save(path, rec)
    assert deploy_repair.run_auto(rec["id"]) == 2, "a second repair process ran beside the one that claimed it"
    assert _schema() == ms.SCHEMA_VERSION + 1 and not deploy_switch.load(path).get("repaired")
    for _ in range(2):
        deploy.settle(now=rec["auto_repair"]["at"] + LATER, alive=lambda pid: False,
                      start=lambda i: started.append(i))
    rec = deploy_switch.load(path)
    assert started == [rec["id"]]
    assert rec["auto_repair"]["state"] == deploy_repair.FAILED and wq.paused()
    assert len([a for a in alerts if "did not repair itself" in a]) == 1
    assert deploy_repair.run_auto(rec["id"]) == 2, "a failed automatic repair ran a second time"


@pytest.mark.sqlite_store
@posix
def test_outside_the_live_home_no_repair_process_is_started(world, alerts):
    job, path = _stranded(world, ds.FLIPPED)
    _old_worker_settles()
    rec = deploy_switch.load(path)
    assert rec["auto_repair"]["state"] == deploy_repair.FAILED and "not the live home" in rec["auto_repair"]["why"]
    assert _schema() == ms.SCHEMA_VERSION + 1 and wq.paused()


@pytest.mark.sqlite_store
@posix
def test_the_repair_process_runs_from_its_module_and_claims_the_record_once(world, alerts):
    job, path = _stranded(world, ds.FLIPPED)
    _old_worker_settles(start=lambda deploy_id: "launchd")
    rec = deploy_switch.load(path)
    argv = [sys.executable, "-m", "harness.deploy_repair", "--auto", str(rec["id"])]
    got = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=300)
    rec = deploy_switch.load(path)
    assert got.returncode == 0, got.stderr[-2000:]
    assert rec["auto_repair"]["state"] == deploy_repair.REPAIRED and rec["repaired"]
    assert _schema() == ms.SCHEMA_VERSION and not wq.paused()
    assert subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=300).returncode == 2


@pytest.mark.skipif(sys.platform != "darwin", reason="the repair is a launchd one-shot on macOS only")
def test_the_repair_starts_as_the_switch_unit_from_this_release(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    assert deploy_repair.start(7) == f"launchd {deploy.SWITCH_LABEL}"
    plist = plistlib.loads((paths.home() / "launchd" / f"{deploy.SWITCH_LABEL}.plist").read_bytes())
    argv = plist["ProgramArguments"]
    assert Path(argv[1]) == REPO / "scripts" / "deploy-switch.sh"
    assert argv[3:] == ["-m", "harness.deploy_repair", "--auto", "7"]
    assert Path(plist["WorkingDirectory"]) == REPO


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/deploy.py:launch:binary:launchctl")
def test_outside_the_live_home_neither_the_repair_nor_the_switch_reaches_launchctl(tmp_path, monkeypatch):
    bin_, called = tmp_path / "bin", tmp_path / "launchctl-called"
    bin_.mkdir()
    (bin_ / "launchctl").write_text(f"#!/bin/sh\ntouch {called}\nexit 0\n", encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(deploy.DeployError, match="not the live home"):
        deploy_repair.start(7)
    with pytest.raises(deploy.DeployError, match="not the live home"):
        deploy.respawn(tmp_path / "7.json", tmp_path)
    assert not called.exists()
