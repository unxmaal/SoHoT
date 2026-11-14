"""A queue deploy has one declared lifecycle: tabled moves, one CAS writer of its row, and a reconciled read of what serves. #1731."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import deploy, deploy_switch, paths
from harness import deploy_state as ds
from harness import workqueue as wq

posix = pytest.mark.skipif(sys.platform == "win32", reason="the deploy link is a symlink, as on launchd hosts")


@pytest.fixture(autouse=True)
def alerts(monkeypatch):
    said = []
    monkeypatch.setattr(deploy, "_alert_here", said.append)
    return said


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", ""])
    p.wait()
    return p.pid


def _row(c, stage: str = ds.BUILDING, release: str = "", previous: str = "/releases/1-old", job_id=None) -> int:
    did = deploy._insert(c, "b" * 40, job_id, Path(previous), "a" * 40, time.time())
    path = [ds.BUILDING, ds.SMOKING, ds.MIGRATING, ds.HANDED_OFF]
    if release:
        assert deploy.move(c, did, ds.BUILDING, ds.BUILDING, ds.JOB, release=release)
    for a, b in zip(path, path[1:]):
        if a == stage:
            break
        assert deploy.move(c, did, a, b, ds.JOB)
    return did


def _get(c, did) -> dict:
    return dict(c.execute("SELECT * FROM deploys WHERE id = ?", (did,)).fetchone())


def _world(tmp_path: Path) -> dict:
    rel, prev = tmp_path / "releases" / "2-new", tmp_path / "releases" / "1-old"
    rel.mkdir(parents=True)
    prev.mkdir(parents=True)
    link = tmp_path / "deploy"
    os.symlink(prev, link)
    return {"release": rel, "previous": prev, "link": link}


# --- the table ------------------------------------------------------------------------------------------------------


def test_the_table_names_every_stage_and_every_running_stage_has_a_way_out():
    named = {s for move in ds.MOVES for s in move} - {ds.NEW}
    assert named == set(ds.STAGES)
    for s in ds.RUNNING:
        assert any(a == s and b != s for a, b in ds.MOVES), f"{s} has no way out"
        assert ds.SETTLE in ds.MOVES[(s, ds.INTERRUPTED)], f"settle cannot close a deploy stranded at {s}"
    assert not [m for m in ds.MOVES if m[0] in ds.OUTCOMES], "nothing leaves an outcome"


LEGAL = [(a, b, w) for (a, b), ws in sorted(ds.MOVES.items()) for w in sorted(ws)]


@pytest.mark.parametrize(("leaves", "enters", "writer"), LEGAL)
def test_each_tabled_move_is_allowed(leaves, enters, writer):
    ds.check(leaves, enters, writer)


ILLEGAL = [
    (ds.NEW, ds.SMOKING, ds.JOB),
    (ds.BUILDING, ds.MIGRATING, ds.JOB),
    (ds.SMOKING, ds.BUILDING, ds.JOB),
    (ds.HANDED_OFF, ds.SWITCHING, ds.JOB),
    (ds.HANDED_OFF, ds.FLIPPED, ds.SWITCH),
    (ds.SWITCHING, ds.SWITCHING, ds.SWITCH),
    (ds.SWITCHING, ds.DEPLOYED, ds.SWITCH),
    (ds.VERIFIED, ds.ROLLING_BACK, ds.SWITCH),
    (ds.INSTALLED, ds.FLIPPED_BACK, ds.SWITCH),
    (ds.RESTORE_FAILED, ds.ROLLED_BACK, ds.SWITCH),
    (ds.RESTORE_FAILED, ds.ROLLBACK_INSTALLED, ds.SWITCH),
    (ds.FLIPPED_BACK, ds.FAILED_FORWARD, ds.SWITCH),
    (ds.HANDED_OFF, ds.FAILED, ds.SWITCH),
    (ds.SMOKING, ds.FAILED, ds.SWITCH),
    (ds.FLIPPED, ds.FAILED, ds.JOB),
    (ds.SWITCHING, ds.FLIPPED, ds.SETTLE),
    (ds.DEPLOYED, ds.ROLLED_BACK, ds.SETTLE),
    (ds.FAILED, ds.INTERRUPTED, ds.SETTLE),
    (ds.INTERRUPTED, ds.DEPLOYED, ds.SWITCH),
]


@pytest.mark.parametrize(("leaves", "enters", "writer"), ILLEGAL)
def test_each_untabled_move_is_refused(leaves, enters, writer):
    with pytest.raises(ds.IllegalMove, match=f"{writer} may not move it"):
        ds.check(leaves, enters, writer)


def test_a_refused_move_writes_nothing_to_the_row():
    with wq._store() as c:
        did = _row(c, ds.SMOKING)
        before = _get(c, did)
        with pytest.raises(ds.IllegalMove):
            deploy.move(c, did, ds.SMOKING, ds.FLIPPED, ds.JOB, detail="nope")
        assert _get(c, did) == before


def test_a_move_from_a_stage_the_row_has_left_loses_and_writes_nothing():
    with wq._store() as c:
        did = _row(c, ds.SMOKING)
        assert not deploy.move(c, did, ds.BUILDING, ds.SMOKING, ds.JOB, detail="stale")
        assert _get(c, did)["stage"] == ds.SMOKING and _get(c, did)["detail"] == ""


def test_two_settles_racing_one_deploy_close_it_and_its_job_once(alerts):
    job = wq.add(["true"], title="deploy", cwd=str(paths.home()), kind=deploy.KIND, output="b" * 40)
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.RUNNING, int(job["id"])))
        c.commit()
        did = _row(c, ds.HANDED_OFF, job_id=int(job["id"]))
        row = dict(_get(c, did))
    deploy_switch.save(deploy.record_path(did), {"stage": ds.SWITCHING, "pid": _dead_pid(), "link": "/nowhere",
                                                 "queue_was_paused": True})
    with wq._store() as a, wq._store() as b:
        first = deploy._settle_one(a, dict(row), time.time(), lambda pid: False)
        second = deploy._settle_one(b, dict(row), time.time(), lambda pid: False)
    assert first == {"deploy": did, "outcome": ds.ABANDONED} and second is None
    assert len(alerts) == 1
    assert wq.get(job["id"])["state"] == wq.FAILED


# --- the switch writes its record through the table -----------------------------------------------------------------


def test_the_switch_refuses_a_record_it_was_not_handed(tmp_path):
    path = tmp_path / "1.json"
    deploy_switch.save(path, {"stage": ds.SWITCHING, "link": str(tmp_path / "deploy"), "log": str(tmp_path / "l")})
    with pytest.raises(ds.IllegalMove):
        deploy_switch.switch(path)
    assert deploy_switch.load(path)["stage"] == ds.SWITCHING


def test_an_outcome_the_table_does_not_reach_ends_failed_and_recorded():
    rec = {"stage": ds.SWITCHING, "outcome": ds.DEPLOYED, "detail": "serving"}
    deploy_switch._end(rec)
    assert rec["outcome"] == rec["stage"] == ds.FAILED
    assert "may not move it from switching to deployed" in rec["detail"]


# --- what serves, reconciled ----------------------------------------------------------------------------------------


@posix
def test_a_failed_restore_settles_failed_forward_and_says_its_own_release_serves(tmp_path, monkeypatch):
    w = _world(tmp_path)

    def gone(backup, db):
        raise ModuleNotFoundError("No module named 'harness'")
    monkeypatch.setattr(deploy_switch, "restore", gone)
    with wq._store() as c:
        did = _row(c, ds.HANDED_OFF, release=str(w["release"]), previous=str(w["previous"]))
    path = deploy.record_path(did)
    deploy_switch.save(path, {
        "id": did, "sha": "b" * 40, "link": str(w["link"]), "release": str(w["release"]),
        "previous": str(w["previous"]), "previous_sha": "a" * 40, "db": str(tmp_path / "x.db"),
        "backup": str(tmp_path / "pre.db"), "migrated": True, "queue_was_paused": True,
        "queue_flag": str(tmp_path / "flag"), "install": ["false"], "rollback_install": ["true"], "verify": [],
        "alert": ["true"], "log": str(tmp_path / "deploy.log"), "stage": ds.HANDED_OFF, "outcome": ""})
    rec = deploy_switch.switch(path)
    assert rec["outcome"] == ds.FAILED_FORWARD
    assert os.path.realpath(w["link"]) == str(w["release"].resolve())
    assert deploy.settle() == [{"deploy": did, "outcome": ds.FAILED_FORWARD}]
    with wq._store() as c:
        d = _get(c, did)
        v = deploy.serving(c, w["link"])
    assert (d["outcome"], d["stage"]) == (ds.FAILED_FORWARD, ds.FAILED_FORWARD)
    assert (v["serves"], v["state"]) == (ds.RELEASE, ds.AGREES)
    assert f"serves this deploy's release {w['release'].resolve()}" in deploy.line({**d, "view": v})


def test_an_older_switch_that_wrote_failed_for_a_failed_restore_settles_failed_forward():
    with wq._store() as c:
        did = _row(c, ds.HANDED_OFF)
    deploy_switch.save(deploy.record_path(did), {"stage": ds.FAILED, "outcome": ds.FAILED, "detail": "restore",
                                                 "restore_failed": "OSError: gone"})
    assert deploy.settle() == [{"deploy": did, "outcome": ds.FAILED_FORWARD}]


@posix
def test_a_crash_between_the_flip_and_its_record_is_reconciled_on_the_next_settle(tmp_path, alerts):
    w = _world(tmp_path)
    with wq._store() as c:
        did = _row(c, ds.HANDED_OFF, release=str(w["release"]), previous=str(w["previous"]))
    deploy_switch.save(deploy.record_path(did), {
        "stage": ds.SWITCHING, "pid": _dead_pid(), "link": str(w["link"]), "release": str(w["release"]),
        "previous": str(w["previous"]), "queue_was_paused": True})
    deploy_switch.flip(w["link"], w["release"])
    with wq._store() as c:
        mid = deploy.serving(c, w["link"])
    assert (mid["stage"], mid["serves"], mid["state"]) == (ds.SWITCHING, ds.RELEASE, ds.SPLIT)
    assert deploy.settle() == [{"deploy": did, "outcome": ds.INTERRUPTED}]
    with wq._store() as c:
        d = _get(c, did)
        after = deploy.serving(c, w["link"])
    assert "SPLIT: switching says the release before it serves, but the deploy link serves this deploy's " \
           f"release {w['release'].resolve()}" in d["detail"]
    assert "SPLIT" in alerts[0]
    assert (after["serves"], after["state"]) == (ds.RELEASE, ds.UNCLAIMED)


@posix
def test_while_it_switches_the_row_reads_the_records_stage_and_the_link(tmp_path):
    w = _world(tmp_path)
    with wq._store() as c:
        did = _row(c, ds.HANDED_OFF, release=str(w["release"]), previous=str(w["previous"]))
        deploy_switch.save(deploy.record_path(did), {"stage": ds.INSTALLED, "pid": os.getpid()})
        deploy_switch.flip(w["link"], w["release"])
        d = _get(c, did)
        v = deploy.serving(c, w["link"])
    assert (d["stage"], v["stage"], v["serves"], v["state"]) == (ds.HANDED_OFF, ds.INSTALLED, ds.RELEASE, ds.AGREES)
    assert "running (installed)" in deploy.line({**d, "view": v})


@posix
def test_a_deployed_row_whose_link_points_back_is_named_split(tmp_path):
    w = _world(tmp_path)
    with wq._store() as c:
        did = _row(c, ds.HANDED_OFF, release=str(w["release"]), previous=str(w["previous"]))
        assert deploy.finish(c, did, ds.DEPLOYED, "serving")
        v = deploy.serving(c, w["link"])
    assert (v["serves"], v["expect"], v["state"]) == (ds.PREVIOUS, ds.RELEASE, ds.SPLIT)
    assert deploy.said(v).startswith("SPLIT: deployed says this deploy's release serves")


@posix
def test_a_lost_record_with_the_link_flipped_settles_interrupted_and_status_names_the_new_release(tmp_path):
    w = _world(tmp_path)
    job = wq.add(["true"], title="deploy", cwd=str(paths.home()), kind=deploy.KIND, output="b" * 40)
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ?, rc = ? WHERE id = ?", (wq.FAILED, 1, int(job["id"])))
        c.commit()
        did = _row(c, ds.HANDED_OFF, release=str(w["release"]), previous=str(w["previous"]), job_id=int(job["id"]))
    deploy_switch.flip(w["link"], w["release"])
    assert deploy.settle() == [{"deploy": did, "outcome": ds.INTERRUPTED}]
    with wq._store() as c:
        v = deploy.serving(c, w["link"])
    assert (v["serves"], v["state"]) == (ds.RELEASE, ds.UNCLAIMED)


def test_a_store_restore_that_rewound_the_row_to_migrating_still_settles_from_the_record():
    with wq._store() as c:
        did = _row(c, ds.MIGRATING)
    deploy_switch.save(deploy.record_path(did), {"stage": ds.ROLLED_BACK, "outcome": ds.ROLLED_BACK,
                                                 "detail": "smoke failed", "rolled_back_from": "b" * 40})
    assert deploy.settle() == [{"deploy": did, "outcome": ds.ROLLED_BACK}]


def test_a_job_lost_mid_migration_is_interrupted_naming_the_backup():
    job = wq.add(["true"], title="deploy", cwd=str(paths.home()), kind=deploy.KIND, output="b" * 40)
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.RUNNING, int(job["id"])))
        c.commit()
        did = _row(c, ds.SMOKING, job_id=int(job["id"]))
        assert deploy.move(c, did, ds.SMOKING, ds.MIGRATING, ds.JOB, backup="/backups/discovery-1-pre9.db")
    assert deploy.settle() == [{"deploy": did, "outcome": ds.INTERRUPTED}]
    with wq._store() as c:
        assert "part-migrated, its backup is /backups/discovery-1-pre9.db" in _get(c, did)["detail"]


def test_a_row_at_a_stage_the_table_does_not_know_is_skipped_and_the_rest_still_settle(capsys):
    with wq._store() as c:
        odd = _row(c, ds.SMOKING)
        c.execute("UPDATE deploys SET stage = 'from_a_newer_release' WHERE id = ?", (odd,))
        c.commit()
        did = _row(c, ds.HANDED_OFF)
    deploy_switch.save(deploy.record_path(did), {"stage": ds.DEPLOYED, "outcome": ds.DEPLOYED, "detail": "serving"})
    assert deploy.settle() == [{"deploy": did, "outcome": ds.DEPLOYED}]
    assert "may not move it from from_a_newer_release" in capsys.readouterr().err
