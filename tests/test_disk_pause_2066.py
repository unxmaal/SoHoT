"""#2066: a disk pause lifts itself once the volume has room, never holds a deploy, and re-alerts while it holds."""
import json
import time

import pytest

from harness import contention, deploy, monitor, pressure, queue_hold, queue_pause, workqueue as wq
from harness import paths
from tests.test_deploy_wait_1672 import _deploy

REASON = "monit: system_data space free 20 GB"
NORMAL = lambda: pressure.Pressure(level=pressure.NORMAL)  # noqa: E731


@pytest.fixture
def disk(monkeypatch):
    free = {"gib": 20.0}
    monkeypatch.setattr(queue_hold, "free_gib", lambda path: free["gib"])
    return free


def _job() -> dict:
    return wq.add(["uv", "run", "python", "-m", "evals.run", "--modality", "code"], title="gpu", cwd=str(paths.home()))


def test_a_disk_pause_lifts_itself_only_past_the_floor_plus_hysteresis(disk):
    monitor.pause_all(REASON)
    assert queue_hold.disk_of(queue_pause.body())["path"] == str(paths.home())
    ok, why = wq.gate(sample=NORMAL)
    assert not ok and f"lifts itself at {monitor.DISK_PAUSE_GIB + monitor.DISK_RESUME_GIB} GiB" in why
    disk["gib"] = monitor.DISK_PAUSE_GIB + monitor.DISK_RESUME_GIB - 1
    assert not wq.gate(sample=NORMAL)[0] and queue_pause.paused(), "above the floor but inside the hysteresis"
    disk["gib"] = monitor.DISK_PAUSE_GIB + monitor.DISK_RESUME_GIB
    ok, why = wq.gate(sample=NORMAL)
    assert ok and not queue_pause.paused() and "paused lifted" in why and "GiB free" in why


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/queue_hold.py:free_gib:except")
def test_a_disk_pause_on_a_volume_it_cannot_read_stays():
    queue_pause.pause(REASON, disk=str(paths.home() / "gone" / "volume"))
    assert queue_hold.free_gib(queue_hold.disk_of(queue_pause.body())["path"]) is None
    ok, why = wq.gate(sample=NORMAL)
    assert not ok and queue_pause.paused() and "unreadable, so it stays paused" in why


def test_an_owner_pause_never_lifts_for_disk_room(disk):
    disk["gib"] = 1000.0
    queue_pause.pause("looking at a lane")
    assert not wq.gate(sample=NORMAL)[0] and queue_pause.paused()


def test_a_disk_pause_lets_the_deploy_through_and_nothing_else(disk):
    monitor.pause_all(REASON)
    _job()
    assert not wq.gate(sample=NORMAL)[0], "a disk pause still holds every other job"
    _deploy(time.time())
    ok, why = wq.gate(sample=NORMAL)
    assert ok and why.endswith("only the deploy starts") and queue_pause.paused()


def test_an_owner_pause_still_holds_a_deploy(disk):
    queue_pause.pause("looking at a lane")
    _deploy(time.time())
    assert not wq.gate(sample=NORMAL)[0]


def test_a_deploy_puts_back_the_pause_it_found(disk):
    monitor.pause_all(REASON)
    found = queue_pause.body()
    note = "deploy 7 of aaaaaaaaaaaa"
    queue_pause.pause(note)
    rec = {"queue_flag": str(queue_pause._pause_flag()), "queue_was_paused": True, "pause_note": note,
           "queue_body": found}
    assert deploy._lift(rec) == "the queue stays paused, as its owner had it"
    assert queue_pause.body() == found and queue_hold.disk_of(queue_pause.body()) is not None


def test_a_held_disk_pause_alerts_again_with_free_space_and_growers(disk):
    monitor.pause_all(REASON)
    now = time.time()
    rows = [{"name": "runs", "path": "/r", "kib": 30 * 1024 ** 2, "why": ""}]
    assert monitor.disk_held(now, measure=lambda: rows) is None, "the pause's own alert counts as the first"
    got = monitor.disk_held(now + contention.PAUSE_REALERT_S + 1, measure=lambda: rows)
    assert got["kind"] == monitor.DISK_HELD and "20.0 GiB free" in got["message"]
    assert f"lifts itself at {monitor.DISK_PAUSE_GIB + monitor.DISK_RESUME_GIB} GiB" in got["message"]
    lines = [json.loads(ln) for ln in monitor.alerts_path().read_text(encoding="utf-8").splitlines()]
    assert [x["kind"] for x in lines] == [monitor.DISK_HELD, "du"] and lines[1]["description"].startswith("growers: runs")
    assert monitor.disk_held(now + contention.PAUSE_REALERT_S + 3600, measure=lambda: rows) is None
    assert monitor.disk_held(now + 2 * contention.PAUSE_REALERT_S + 2, measure=lambda: rows) is not None
    disk["gib"] = 100.0
    assert monitor.disk_held(now + 3 * contention.PAUSE_REALERT_S + 3, measure=lambda: rows) is None
    assert not queue_pause.paused() and not monitor._held_alerted().exists()
