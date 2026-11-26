"""The Needs-you band follows monit's live state and a live deploy's own pause. #2143, #2141."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from harness import monitor, needs_you, proc_identity, queue_hold, queue_pause, status_view
from test_needs_you_2134 import NOW, _mon, cond, gather, keys

LOW = "space free 40.4 GB matches resource limit [space free < 50 GB]"
VOLUME = "models_volume   {}   Filesystem"


def _volume_low(home, **extra):
    monitor.record({"at": NOW - 13 * 86400, "kind": "volume-low", "service": "models_volume", "description": LOW,
                    "event": "Resource limit matched", **extra}, home)


def _began(home):
    monitor.record({"at": NOW - 3600, "kind": needs_you.KIND, "service": needs_you.SERVICE + "monit-models_volume",
                    "event": "began", "description": f"models_volume needs attention since 11-13 23:36: {LOW}"}, home)


def test_an_open_alert_whose_service_monit_reports_ok_is_not_in_the_band(tmp_path):
    _volume_low(tmp_path)
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format("OK"),)))
    assert "monit-models_volume" not in keys(r) and r["stops"]["monit"]["open"] == []
    assert needs_you.sync(r, tmp_path)["began"] == []
    assert [a for a in monitor.alerts(0, tmp_path) if a["kind"] == needs_you.KIND] == []


def test_an_open_alert_whose_service_monit_reports_failing_is_in_the_band_and_alerted(tmp_path):
    _volume_low(tmp_path)
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format("Resource limit matched"),)))
    assert cond(r, "monit-models_volume")["since"] == NOW - 13 * 86400
    assert "monit-models_volume" in needs_you.sync(r, tmp_path)["began"]


def test_the_replayed_stale_alert_is_closed_not_re_raised_and_its_needs_you_record_clears(tmp_path):
    _volume_low(tmp_path)
    _began(tmp_path)
    ok = gather(tmp_path, mon=_mon(rows=(VOLUME.format("OK"),)))
    sent = lambda: [a for a in monitor.alerts(0, tmp_path) if a["kind"] in (needs_you.KIND, monitor.RECOVERED)]  # noqa: E731
    for _ in range(needs_you.CLEAR_PASSES):
        got = needs_you.sync(ok, tmp_path)
        assert got["began"] == []
    assert got["cleared"] == ["monit-models_volume"]
    assert [a["kind"] for a in sent()] == [needs_you.KIND, monitor.RECOVERED]


def test_a_monit_that_cannot_be_read_leaves_the_logged_alert_open(tmp_path):
    _volume_low(tmp_path)
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format("OK"),), running=False))
    assert "monit-models_volume" in keys(r)


def test_a_service_monit_is_not_watching_stays_open(tmp_path):
    _volume_low(tmp_path)
    assert "monit-models_volume" in keys(gather(tmp_path, mon=_mon(rows=(VOLUME.format("Not monitored"),))))


def _flag(why, pid, began_at, holder=False, deploy=18):
    stamp = time.strftime(queue_hold._STAMP, time.localtime(began_at))
    lines = [f"{stamp} {why}"]
    if deploy:
        lines.append(queue_hold._DEPLOY + json.dumps({"id": None if deploy is True else deploy}))
    if holder:
        lines.append(queue_hold._TAG + json.dumps(proc_identity.identity(pid)))
    lines.append(queue_hold._BY + json.dumps({"pid": pid, "ppid": 1, "argv": ["cli.py", "deploy", "run", "18065209"]}))
    queue_pause._pause_flag().write_text("\n".join(lines), encoding="utf-8")


def _after_start() -> float:
    return proc_identity.began(os.getpid()) + 5


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_a_pause_held_by_a_live_deploy_is_the_deploy_tile_not_the_band(tmp_path):
    _flag("deploy 18 of 180652093a1b", os.getpid(), _after_start())
    r = gather(tmp_path)
    assert "queue-paused" not in keys(r)
    assert r["deploy"]["in_progress"]["id"] == 18
    assert status_view._deploy(r["deploy"], NOW)[1] == "deploy 18 in progress"


def test_a_live_holder_line_pause_for_a_deploy_install_is_not_the_band_either(tmp_path):
    _flag("held for a deploy by pid 1", os.getpid(), _after_start(), holder=True)
    r = gather(tmp_path)
    assert "queue-paused" not in keys(r) and r["deploy"]["in_progress"]["live"]
    assert status_view._deploy(r["deploy"], NOW)[1] == "deploy in progress"


def test_a_deploys_pause_whose_process_is_gone_is_a_stuck_pause_with_resume(tmp_path):
    _flag("deploy 18 of 180652093a1b", _dead_pid(), NOW - 60)
    r = gather(tmp_path)
    c = cond(r, "queue-paused")
    assert "stuck" in c["title"] and [f["action"] for f in c["fix"]] == ["queue_resume"]
    assert "in_progress" not in r["deploy"]


def test_a_pid_started_after_the_pause_is_a_reused_pid_not_its_holder(tmp_path):
    _flag("deploy 18 of 180652093a1b", os.getpid(), NOW - 10 * 86400)
    assert "stuck" in cond(gather(tmp_path), "queue-paused")["title"]


def test_an_owners_pause_still_shows_with_resume(tmp_path):
    queue_pause.pause("owner: looking into a failure")
    c = cond(gather(tmp_path), "queue-paused")
    assert c["title"] == "The queue is paused: no job starts" and [f["action"] for f in c["fix"]] == ["queue_resume"]


def test_a_holder_line_pause_whose_holder_is_gone_is_a_stuck_pause(tmp_path):
    _flag("held for a deploy by pid 1", _dead_pid(), NOW - 60, holder=True)
    r = gather(tmp_path)
    assert "stuck" in cond(r, "queue-paused")["title"] and "in_progress" not in r["deploy"]


def test_a_pause_is_a_deploys_by_what_the_flag_records_not_by_what_its_reason_says(tmp_path):
    _flag("deploy 18 of 180652093a1b", os.getpid(), _after_start(), deploy=None)
    assert "stuck" not in cond(gather(tmp_path), "queue-paused")["title"]
    queue_pause.pause("deploy 7 of abc", deploy=7)
    assert queue_hold.deploy_hold(queue_pause.body())["id"] == 7
