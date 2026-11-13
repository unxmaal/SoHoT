"""A switch record left at a switch stage, its switch gone and its release not served, is closed abandoned once. #1971."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from test_deploy_1506 import BASH, _dead_pid, _deploys, alerts, posix, world  # noqa: F401 - fixtures
from test_deploy_resume_1753 import _handed

from harness import deploy, deploy_switch, proc_identity
from harness import deploy_state as ds
from harness import workqueue as wq

LATER = deploy.HANDOFF_GRACE_S + 1


def _settle_twice() -> list:
    return [[d["outcome"] for d in deploy.settle(now=time.time() + LATER + i)] for i in range(2)]


def _left_by_an_older_settle(world, pid: int, **rec_more) -> tuple[dict, Path]:
    """Deploy 15's shape: a pre-#1753 record at switching (no identity, no resume), its row closed interrupted."""
    job, path = _handed(world, migrate=False)
    rec = deploy_switch.load(path)
    rec.pop("identity", None)
    rec.update(stage=ds.SWITCHING, pid=pid, switch_started=time.time(), **rec_more)
    deploy_switch.save(path, rec)
    (row,) = _deploys()
    with wq._store() as c:
        assert deploy.finish(c, row["id"], deploy.INTERRUPTED, "the switch stopped at switching without an outcome")
        deploy._close_job(c, job["id"], wq.FAILED, None, "interrupted", time.time())
    return row, path


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/deploy_state.py:MOVES:abandoned")
@pytest.mark.sqlite_store
@posix
def test_a_pre_1753_record_stuck_switching_with_a_dead_pid_is_closed_once(world, alerts):
    row, path = _left_by_an_older_settle(world, _dead_pid())
    assert _settle_twice() == [[ds.ABANDONED], []]
    rec = deploy_switch.load(path)
    assert (rec["stage"], rec["outcome"], ds.outcome_of(rec)) == (ds.SWITCHING, ds.FAILED, ds.ABANDONED)
    assert "its process is gone" in rec["abandoned"] and "not its release" in rec["abandoned"]
    (after,) = _deploys()
    assert (after["stage"], after["outcome"]) == (deploy.INTERRUPTED, deploy.INTERRUPTED), "a closed row stays closed"
    assert len(alerts) == 1 and f"deploy {row['id']} of {row['sha'][:12]} abandoned: " in alerts[0]


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("how", ["pid alive, no identity", "same() True", "same() None"])
def test_a_live_switch_record_is_left_alone(world, alerts, monkeypatch, how):
    more = {} if how.startswith("pid") else {"identity": proc_identity.identity(os.getpid())}
    if how == "same() None":
        monkeypatch.setattr(proc_identity, "same", lambda rec: None)
    _, path = _left_by_an_older_settle(world, os.getpid(), **more)
    before = path.read_bytes()
    assert _settle_twice() == [[], []]
    assert path.read_bytes() == before and alerts == []


@pytest.mark.sqlite_store
@posix
def test_a_dead_switch_whose_release_serves_is_left_alone(world, alerts):
    _, path = _left_by_an_older_settle(world, _dead_pid())
    rec = deploy_switch.load(path)
    deploy_switch.flip(Path(rec["link"]), Path(rec["release"]))
    assert _settle_twice() == [[], []]
    assert not deploy_switch.load(path).get("outcome") and alerts == []


@pytest.mark.sqlite_store
@posix
def test_a_dead_switch_settle_cannot_start_again_ends_abandoned_in_row_and_record_and_alerts_once(world, alerts):
    job, path = _handed(world, migrate=False)
    rec = deploy_switch.load(path)
    rec.update(stage=ds.SWITCHING, pid=_dead_pid(), switch_started=time.time())
    deploy_switch.save(path, rec)
    assert _settle_twice() == [[ds.ABANDONED], []]
    (row,) = _deploys()
    assert (row["stage"], row["outcome"]) == (ds.ABANDONED, ds.ABANDONED) and "starting it again failed" in row["detail"]
    rec = deploy_switch.load(path)
    assert ds.outcome_of(rec) == ds.ABANDONED and wq.get(job["id"])["state"] == wq.FAILED
    assert len(alerts) == 1 and " abandoned: " in alerts[0]
    # An older release reads the record as failed: a move its MOVES list, and an outcome its recover skips.
    assert rec["outcome"] == ds.FAILED
    ds.check(ds.HANDED_OFF, ds.FAILED, ds.SETTLE)
    ds.check(ds.SWITCHING, ds.FAILED, ds.SETTLE)


@pytest.mark.sqlite_store
@posix
def test_a_dead_switch_whose_row_is_open_is_left_to_be_resumed_not_abandoned(world, alerts):
    _, path = _handed(world, migrate=False)
    rec = deploy_switch.load(path)
    rec.update(stage=ds.SWITCHING, pid=_dead_pid(), switch_started=time.time())
    deploy_switch.save(path, rec)
    with wq._store() as c:
        assert deploy._orphans(c, time.time() + LATER, lambda pid: False) == []
    assert not deploy_switch.load(path).get("outcome") and alerts == []
