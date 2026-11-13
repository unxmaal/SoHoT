"""A recovery pages only when its failure paged, and says how long it lasted; memory flaps are one episode (#1870)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time

import pytest

from harness import monitor
from tests.test_monitor_1485 import _Hook, _env_file, _monit_env, _spec, hook, live  # noqa: F401

T = 1_794_500_000.0
UP = "connection succeeded to [127.0.0.1]:4000 [TCP/IP]"


def _alert(kind, service, desc, at):
    return monitor.alert(kind, _monit_env(service, desc), clock=lambda: at, measure=lambda: [])


def _rows():
    return [json.loads(ln) for ln in monitor.alerts_path().read_text(encoding="utf-8").splitlines()]


def test_a_recovery_whose_failure_never_alerted_sends_nothing(live, hook):
    _env_file(hook)
    _alert("service", "service_mlx", "port 8081 closed", T)
    got = _alert(monitor.RECOVERED, "service_gateway", UP, T + 300)
    assert live == [("desktop", monitor.TITLE, "service: service_mlx: port 8081 closed")]
    assert len(_Hook.bodies) == 1 and got["desktop"].startswith("not sent: ") and got["webhook"].startswith("not sent")
    row = _rows()[-1]
    assert row["held"] and row["kind"] == monitor.RECOVERED and row["service"] == "service_gateway"
    assert {"at", "kind", "service", "event", "description", "message", "desktop", "webhook"} <= set(row)


def test_a_second_recovery_of_one_failure_sends_nothing(live, hook):
    _env_file(hook)
    _alert("memory", "memory_pressure", "memory pressure level 2", T)
    _alert(monitor.RECOVERED, "memory_pressure", "memory pressure level 1", T + 7200)
    _alert(monitor.RECOVERED, "memory_pressure", "memory pressure level 1", T + 9000)
    assert len(live) == 2 and len(_Hook.bodies) == 2
    assert [bool(r.get("held")) for r in _rows()] == [False, False, True]
    assert [monitor.line(r).endswith(" (not sent)") for r in _rows()] == [False, False, True]


def test_a_recovery_after_an_alerted_failure_alerts_once_and_names_the_down_time(live, hook):
    _env_file(hook)
    _alert("service", "service_gateway", "failed protocol test at [127.0.0.1]:4000", T)
    got = _alert(monitor.RECOVERED, "service_gateway", UP, T + 1500)
    assert len(live) == 2 and len(_Hook.bodies) == 2
    # The port was closed one cycle before monit's second failed check alerted.
    lead = (monitor.cycles(monitor.SERVICE_DOWN_S) - 1) * monitor.CYCLE_S
    assert got["message"] == f"recovered: service_gateway: {UP}; down about 30m (alerted " \
                             f"{time.strftime('%m-%d %H:%M', time.localtime(T))})"
    assert live[1][2] == got["message"] and json.loads(_Hook.bodies[1])["content"].endswith(got["message"])
    row = _rows()[-1]
    assert row["down_s"] == 1500 + lead and row["failed_at"] == T and not row.get("held")


def test_a_memory_recovery_names_the_episode_without_the_calm_wait(live):
    _alert("memory", "memory_pressure", "memory pressure level 2", T)
    got = _alert(monitor.RECOVERED, "memory_pressure", "memory pressure level 1", T + 7200)
    lead = (monitor.cycles(monitor.MEMORY_WARN_S) - 1) * monitor.CYCLE_S
    lag = (monitor.cycles(monitor.MEMORY_CALM_S) - 1) * monitor.CYCLE_S
    assert got["down_s"] == 7200 + lead - lag == 4200
    assert "; episode about 1h 10m (alerted " in got["message"] and len(live) == 2


def test_memory_recovers_only_after_its_calm_seconds_in_cycles(tmp_path, monkeypatch):
    line = next(ln for ln in monitor.render(_spec(tmp_path)).splitlines() if "monit-alert.sh memory" in ln)
    assert f'else if succeeded for {monitor.cycles(monitor.MEMORY_CALM_S)} cycles then exec "' in line
    assert line.endswith('monit-alert.sh recovered"') and monitor.cycles(monitor.MEMORY_CALM_S) > 1
    service = next(ln for ln in monitor.render(_spec(tmp_path)).splitlines() if "monit-alert.sh service" in ln)
    assert "else if succeeded then exec" in service


def _scratch_monit(tmp_path, monkeypatch, statuses: list[int]) -> str:
    """The rendered memory_pressure check on a 1 s cycle, fed `statuses` one per check; its actions, in order."""
    monkeypatch.setattr(monitor, "CYCLE_S", 1)
    monkeypatch.setattr(monitor, "MEMORY_WARN_S", 2)
    monkeypatch.setattr(monitor, "MEMORY_CALM_S", 3)
    d = tmp_path / "m"
    d.mkdir()
    (d / "seq").write_text("".join(f"{s}\n" for s in statuses), encoding="utf-8")
    prog, act, trace = d / "prog.sh", d / "act.sh", d / "trace"
    prog.write_text(f'#!/bin/sh\ns=$(head -1 "{d}/seq"); tail -n +2 "{d}/seq" > "{d}/seq.t"; mv "{d}/seq.t" "{d}/seq"\n'
                    'exit ${s:-0}\n', encoding="utf-8")
    act.write_text(f'#!/bin/sh\necho "$1" >> "{trace}"\n', encoding="utf-8")
    prog.chmod(0o755)
    act.chmod(0o755)
    text = monitor.render(_spec(tmp_path))
    block = text[text.index("check program memory_pressure"):]
    block = block[:block.index("\n\n")]
    block = re.sub(r'with path "[^"]*monit-pressure\.sh"', f'with path "{prog}"', block)
    block = re.sub(r'exec "[^"]*monit-alert\.sh ', f'exec "{act} ', block)
    rc = d / "rc"
    rc.write_text(f"set daemon 1\nset log {d}/monit.log\nset pidfile {d}/monit.pid\nset idfile {d}/monit.id\n"
                  f"set statefile {d}/monit.state\n{block}\n", encoding="utf-8")
    rc.chmod(0o600)
    monit = shutil.which("monit")
    try:
        started = subprocess.run([monit, "-c", str(rc)], capture_output=True, text=True, timeout=30)
        assert started.returncode == 0, started.stdout + started.stderr
        deadline = time.monotonic() + len(statuses) + 15
        while time.monotonic() < deadline and (d / "seq").read_text(encoding="utf-8").strip():
            time.sleep(0.2)
        time.sleep(6)
    finally:
        subprocess.run([monit, "-c", str(rc), "quit"], capture_output=True, text=True, timeout=30)
    return trace.read_text(encoding="utf-8") if trace.exists() else ""


@pytest.mark.skipif(shutil.which("monit") is None, reason="monit is not installed")
def test_memory_flapping_under_monit_alerts_once_per_episode(tmp_path, monkeypatch):
    got = _scratch_monit(tmp_path, monkeypatch, [1, 1, 1, 0, 1, 1, 1, 0, 0, 1, 0, 0, 0, 0, 0])
    assert got.split() == ["memory", "recovered"]
