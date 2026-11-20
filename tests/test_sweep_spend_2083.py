"""A sweep never yields its ceiling to a deploy the queue will not start, and the status page goes red when nothing is screened. #2083."""
from __future__ import annotations

import os
import signal
import time
import types

import pytest

from harness import ceiling, deploy, heartbeat, paths, queue_hold, queue_pause
from harness import memory_store as ms
from harness import status_page as sp
from harness import status_view as sv
from harness import workqueue as wq
from harness.commands import loop as loop_cmd
from tests.test_deploy_hold_1675 import _leads, loop_beat  # noqa: F401 - fixtures
from tests.test_deploy_wait_1672 import _deploy
from tests.test_status_view_2078 import NOW, _gather, _tiles

def _owner_pause():
    queue_pause.pause("owner looking at the disk")


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 is POSIX")
def test_a_deploy_the_paused_queue_will_not_start_does_not_take_the_sweep(loop_beat):
    _deploy(time.time())
    _owner_pause()
    assert queue_pause.deploy_held().startswith("paused")
    asked = []
    assert wq.preempt_for_deploy(evals=lambda pid: asked.append(pid) or [], signal_=signal.SIGUSR1) == []
    assert asked == [] and not loop_cmd._ASKED
    for tier in ("inspect", "screen", "measure"):
        loop_cmd._beat(tier)


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 is POSIX")
def test_a_disk_pause_still_lets_the_deploy_through_so_the_sweep_yields(loop_beat):
    _deploy(time.time())
    queue_pause.pause("disk full", disk=str(paths.home()))
    assert queue_pause.deploy_held() == ""
    assert wq.preempt_for_deploy(evals=lambda pid: [], signal_=signal.SIGUSR1)
    with pytest.raises(loop_cmd.DeployDue):
        loop_cmd._beat("screen")


def test_a_deploy_held_by_an_owner_pause_is_not_in_flight_but_one_holding_the_queue_for_its_install_is():
    _deploy(time.time())
    assert loop_cmd._deploy_in_flight()
    _owner_pause()
    assert not loop_cmd._deploy_in_flight()
    queue_pause.resume()
    queue_pause.hold_for_deploy(stop=lambda *a: "", tree=lambda pid: [])
    assert queue_pause.deploy_held() == "" and loop_cmd._deploy_in_flight()
    queue_pause.release_for_deploy()
    deploy.pause()
    assert queue_pause.deploy_held() == "deploys are paused (soh deploy resume)"
    deploy.resume()


def test_a_yielded_sweep_goes_on_at_once_with_its_ceiling_when_the_queue_is_paused_after(capsys):
    _deploy(time.time())
    _owner_pause()

    def sleep(s):
        raise AssertionError("waited on a deploy that cannot start")
    got = loop_cmd._after_deploy(3600.0, sleep=sleep, clock=lambda: 0.0)
    assert got == loop_cmd.YIELDED
    out = capsys.readouterr().out
    assert "the deploy cannot start (paused" in out and "1h 00m" in out


def test_a_crash_in_upkeep_is_named_in_the_ceiling_summary_not_ran_out_of_measurements(monkeypatch, capsys):
    monkeypatch.setattr("harness.router.settle", lambda why: None)
    monkeypatch.setattr(loop_cmd, "_publish_if_enabled", lambda: "")
    notes = {}
    monkeypatch.setattr("harness.heartbeat.note", lambda k, v: notes.update({k: v}))

    def spend(a, rc, failed, sweep):
        raise ValueError("not queued: the job's code speaks schema 107")
    monkeypatch.setattr(loop_cmd, "_loop_spend", spend)
    sweep = ceiling.Sweep(6 * 3600)
    with pytest.raises(ValueError):
        loop_cmd._spend_and_settle(types.SimpleNamespace(), 0, [], sweep)
    out = capsys.readouterr().out
    assert "ran out of measurements" not in out
    assert "unused: " in out and "a ValueError stopped the sweep before its ceiling: not queued" in out
    assert "ValueError" in notes[heartbeat.CEILING_UNUSED]["why"]


def _waiting_and_ran(at, elsewhere=None):
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name="org/peer-4b", source="t", kind="weights", lane="decide", why="seeded"))
        ms.decide(conn, "org/peer-4b", "queued", tier="inspect", detail="fits: 2.9 GiB")
        mid = ms.remember_machine(conn)
        other = conn.execute("INSERT INTO machines (fingerprint, first_seen, last_seen) VALUES (?,?,?)",
                             ("fp-node", NOW, NOW)).lastrowid if elsewhere is not None else None
        for path, t, m in (("20261115-0241-adopt-svg", at, mid), ("20261119-claims-node", elsewhere, other)):
            if t is not None:
                conn.execute("INSERT INTO runs (path, lane, tier, machine_id, generated_at, recorded_at) "
                             "VALUES (?,?,?,?,?,?)", (path, "svg", "measure", m, t, t))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                       site="harness/status_page.py:spend:runs")
@pytest.mark.parametrize("days", [4.5, None])
def test_candidates_waiting_with_no_screen_for_days_is_red(tmp_path, days):
    _waiting_and_ran(None if days is None else NOW - days * 86400, elsewhere=NOW - 600)
    r = _gather(tmp_path)
    state, head = _tiles(r)["discovery"]
    assert state == sv.BAD and head.startswith("no screen") and "1 waiting" in head
    assert any(b.startswith("discovery screens nothing") for b in r["banner"])
    assert any("1 candidate(s) waiting" in x for x in sp.lines(r)["Discovery"])


def test_a_recent_screen_or_an_empty_queue_is_not_red(tmp_path):
    _waiting_and_ran(NOW - 3600)
    r = _gather(tmp_path)
    assert _tiles(r)["discovery"][0] == sv.OK
    assert not any(b.startswith("discovery screens nothing") for b in r["banner"])
    assert not sp.spend_stalled({"last_run_at": None, "waiting": 0}, NOW)
    assert not sp.spend_stalled({"error": "store down"}, NOW)
    assert sp.spend_stalled({"last_run_at": NOW - sp.SPEND_STALE_S - 1, "waiting": 3}, NOW)
    assert not sp.spend_stalled({"last_run_at": NOW - sp.SPEND_STALE_S + 60, "waiting": 3}, NOW)
