"""A deploy's own transients (its pause outliving the worker, the gateway it restarts) do not page the owner. #2153."""
from __future__ import annotations

import json
import os

from harness import deploy, monitor, needs_you, proc_identity
from test_needs_you_2134 import NOW, _mon, gather, keys
from test_needs_you_live_2143 import _dead_pid, _flag

GATEWAY_DOWN = _mon(rows=("service_gateway   Connection failed   Remote Host 127.0.0.1:4000",))


def _record(deploy_id, *, outcome="", finished=None, switch_pid=None, stage="switching"):
    rec = {"id": deploy_id, "stage": stage, "outcome": outcome, "run_pid": _dead_pid(), "switch_started": NOW - 60}
    if switch_pid:
        rec.update(pid=switch_pid, identity=proc_identity.identity(switch_pid))
    if finished is not None:
        rec["finished_at"] = finished
    deploy.record_path(deploy_id).write_text(json.dumps(rec), encoding="utf-8")


def _stuck(r):
    return "queue-paused" in keys(r)


def _pause(tmp_path):
    _flag("deploy 150 of be19b2953d56", _dead_pid(), NOW - 60, deploy=150)


def test_the_pause_of_a_deploy_whose_switch_is_still_working_does_not_page(tmp_path):
    _pause(tmp_path)
    _record(150, switch_pid=os.getpid())
    r = gather(tmp_path)
    assert not _stuck(r) and needs_you.sync(r, tmp_path)["began"] == []


def test_the_pause_of_a_deploy_that_just_deployed_waits_for_a_lift_pass_before_paging(tmp_path):
    _pause(tmp_path)
    _record(150, outcome="deployed", finished=NOW - needs_you.SETTLE_S + 30, stage="deployed")
    assert not _stuck(gather(tmp_path))


def test_a_failed_deploy_is_given_the_same_lift_pass(tmp_path):
    _pause(tmp_path)
    _record(150, outcome="failed", finished=NOW - 10, stage="failed")
    assert not _stuck(gather(tmp_path))


def test_the_pause_pages_once_the_deploy_ended_longer_ago_than_a_lift_pass_takes(tmp_path):
    _pause(tmp_path)
    _record(150, outcome="deployed", finished=NOW - needs_you.SETTLE_S - 30, stage="deployed")
    r = gather(tmp_path)
    assert _stuck(r) and needs_you.sync(r, tmp_path)["began"] == ["queue-paused"]


def test_a_deploy_pause_with_no_record_pages(tmp_path):
    _pause(tmp_path)
    assert _stuck(gather(tmp_path))


def test_a_deploy_record_whose_processes_are_all_gone_and_no_outcome_pages(tmp_path):
    _pause(tmp_path)
    _record(150, switch_pid=_dead_pid())
    assert _stuck(gather(tmp_path))


def test_another_deploys_record_does_not_excuse_this_deploys_pause(tmp_path):
    _pause(tmp_path)
    _record(151, switch_pid=os.getpid())
    assert _stuck(gather(tmp_path))


def test_the_settle_bound_is_two_monit_cycles():
    assert needs_you.SETTLE_S == 2 * monitor.CYCLE_S


def test_the_gateway_check_failing_during_a_deploy_does_not_page(tmp_path):
    _record(150, switch_pid=os.getpid())
    r = gather(tmp_path, mon=GATEWAY_DOWN)
    assert "check-service_gateway" not in keys(r) and needs_you.sync(r, tmp_path)["began"] == []


def test_the_gateway_check_failing_just_after_a_deploy_ended_does_not_page(tmp_path):
    _record(150, outcome="deployed", finished=NOW - 60, stage="deployed")
    assert "check-service_gateway" not in keys(gather(tmp_path, mon=GATEWAY_DOWN))


def test_a_gateway_down_longer_than_the_bound_after_a_deploy_pages(tmp_path):
    _record(150, outcome="deployed", finished=NOW - needs_you.SETTLE_S - 30, stage="deployed")
    r = gather(tmp_path, mon=GATEWAY_DOWN)
    assert "check-service_gateway" in keys(r) and "check-service_gateway" in needs_you.sync(r, tmp_path)["began"]


def test_a_gateway_down_with_no_deploy_at_all_pages(tmp_path):
    assert "check-service_gateway" in keys(gather(tmp_path, mon=GATEWAY_DOWN))


def test_a_monit_service_alert_during_a_deploy_does_not_page_and_after_it_does(tmp_path):
    monitor.record({"at": NOW - 120, "kind": "service", "service": "service_gateway",
                    "description": "failed protocol test", "event": "Connection failed"}, tmp_path)
    _record(150, switch_pid=os.getpid())
    assert "service-service_gateway" not in keys(gather(tmp_path, mon=GATEWAY_DOWN))
    _record(150, outcome="deployed", finished=NOW - needs_you.SETTLE_S - 30, stage="deployed")
    assert "service-service_gateway" in keys(gather(tmp_path, mon=GATEWAY_DOWN))


def test_a_check_that_is_not_a_service_still_pages_during_a_deploy(tmp_path):
    _record(150, switch_pid=os.getpid())
    r = gather(tmp_path, mon=_mon(rows=("models_volume   Resource limit matched   Filesystem",)))
    assert "check-models_volume" in keys(r)
