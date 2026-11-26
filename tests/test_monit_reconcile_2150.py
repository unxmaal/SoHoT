"""A monit restart drops the recovery it owed; the pass writes it from monit's live state. #2150."""
from __future__ import annotations

import argparse

from harness import monitor, needs_you, status_page
from harness.commands import needs_you as cmd
from test_needs_you_2134 import _mon, gather
from test_needs_you_live_2143 import VOLUME, _volume_low


def _pass(tmp_path, state):
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format(state),)))
    return needs_you.reconcile_monit(r["monitor"], tmp_path)


def test_an_open_alert_whose_service_monit_reports_ok_gets_one_reconciled_recovered_line(tmp_path):
    _volume_low(tmp_path)
    got = _pass(tmp_path, "OK")
    assert [(e["kind"], e["service"], e["event"]) for e in got] == [(monitor.RECOVERED, "models_volume", "reconciled")]
    assert monitor.still_open(monitor.alerts(0, tmp_path)) == []
    assert "reconciled" in monitor.alerts(0, tmp_path)[-1]["message"]
    assert monitor.line(monitor.alerts(0, tmp_path)[-1]).endswith("(not sent)")
    assert _pass(tmp_path, "OK") == [] and len(monitor.alerts(0, tmp_path)) == 2


def test_a_service_still_failing_gets_no_recovered_line(tmp_path):
    _volume_low(tmp_path)
    assert _pass(tmp_path, "Resource limit matched") == []
    assert [a["kind"] for a in monitor.alerts(0, tmp_path)] == ["volume-low"]
    assert [a["service"] for a in monitor.still_open(monitor.alerts(0, tmp_path))] == ["models_volume"]


def test_a_monit_that_is_not_running_or_still_initializing_closes_nothing(tmp_path):
    _volume_low(tmp_path)
    assert _pass(tmp_path, "Initializing") == []
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format("OK"),), running=False))
    assert needs_you.reconcile_monit(r["monitor"], tmp_path) == []
    assert len(monitor.alerts(0, tmp_path)) == 1


def test_only_the_passing_service_is_closed(tmp_path):
    _volume_low(tmp_path)
    monitor.record({"at": 1.0, "kind": "service", "service": "service_mlx", "description": "port 8081 closed"}, tmp_path)
    r = gather(tmp_path, mon=_mon(rows=(VOLUME.format("OK"), "service_mlx   Connection failed   Remote Host")))
    assert [e["service"] for e in needs_you.reconcile_monit(r["monitor"], tmp_path)] == ["models_volume"]
    assert [a["service"] for a in monitor.still_open(monitor.alerts(0, tmp_path))] == ["service_mlx"]


def test_the_alert_pass_reconciles_before_it_alerts(monkeypatch):
    seen = []
    monkeypatch.setattr(status_page, "gather", lambda light=False: {"monitor": {"m": 1}})
    monkeypatch.setattr(needs_you, "conditions", lambda r: [])
    monkeypatch.setattr(needs_you, "reconcile_monit", lambda live, home=None: seen.append(("reconcile", live)))
    monkeypatch.setattr(needs_you, "sync", lambda r: seen.append(("sync", None)) or {})
    assert cmd.cmd_needs_you(argparse.Namespace(alert=True)) == 0
    assert [k for k, _ in seen] == ["reconcile", "sync"] and seen[0][1] == {"m": 1}
    seen.clear()
    cmd.cmd_needs_you(argparse.Namespace(alert=False))
    assert seen == []
