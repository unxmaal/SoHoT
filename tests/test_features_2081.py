"""The status page's feature table: each row read from the source the harness reads (#2081)."""
from __future__ import annotations

import json
import plistlib
import time
from pathlib import Path

import pytest

from harness import features as f
from harness import hold
from harness import memory_store as ms
from harness import paths
from harness import status_view as sv

NOW = time.time()
PREFIX = "com.example.test"
SPEECH = [("harness.audio", "speech_enabled", "SOHOT_SPEECH")]
NODES = """nodes:
  - name: node-a
    api_base: http://node-a.example:8080/v1
    engine: llama-server
    models: [m]
    parked: true
  - name: node-b
    api_base: http://node-b.example:8080/v1
    engine: llama-server
    models: [m]
    lanes: [decide]
"""


def _root(tmp_path: Path) -> tuple[Path, Path, Path]:
    root, agents, logs = tmp_path / "repo", tmp_path / "agents", tmp_path / "logs"
    for d in (root / "scripts", agents, logs):
        d.mkdir(parents=True)
    (root / "scripts" / "launchd.sh").write_text('SERVICES="ds4 gateway deploy audit"\n', encoding="utf-8")
    (root / "scripts" / "serve-ds4.sh").write_text('echo "ds4: nothing to serve (no spec)"\nexit 0\n', encoding="utf-8")
    (root / "scripts" / "serve-gateway.sh").write_text("exec litellm\n", encoding="utf-8")
    for unit, env in (("ds4", {}), ("gateway", {}), ("deploy", {"SOHOT_SPEECH": "no"})):
        (agents / f"{PREFIX}.{unit}.plist").write_bytes(plistlib.dumps({"Label": unit, "EnvironmentVariables": env}))
    (logs / "ds4.log").write_text("=== ds4 start\nds4: nothing to serve (no spec)\n", encoding="utf-8")
    return root, agents, logs


def _gather(tmp_path, conn, **kw):
    root, agents, logs = _root(tmp_path)
    (tmp_path / "nodes.yaml").write_text(NODES, encoding="utf-8")
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    args = {"root": root, "agents": agents, "logs": logs, "listed": {"ds4": (None, 0), "gateway": (321, 0)},
            "nodes_file": tmp_path / "nodes.yaml", "settings": tmp_path / "settings.json", "pinned": {"code": {}},
            "defaults": {"code": "llamacpp:m", "decide": "llamacpp:d", "image": "mflux:dev"}, "readers": SPEECH}
    args.update(kw)
    import harness.install_env as ie
    old = ie.PREFIX
    ie.PREFIX = PREFIX
    try:
        return f.gather(conn, NOW, {"paused": False}, **args)["rows"]
    finally:
        ie.PREFIX = old


def _by(rows, kind, name) -> dict:
    return next(r for r in rows if r["kind"] == kind and r["name"] == name)


def test_a_parked_node_a_paused_switch_and_an_idle_engine_each_read_as_such(tmp_path):
    conn = ms.connect()
    try:
        hold.hold(conn, "owner: the test rebuild", now=NOW - 60)
        rows = _gather(tmp_path, conn)
    finally:
        conn.close()
    assert _by(rows, "node", "node-a")["state"] == f.PARKED
    assert _by(rows, "node", "node-b")["state"] == f.ON
    held = _by(rows, "switch", f"{hold.BENCHMARKS} hold")
    assert held["state"] == f.PAUSED and "the test rebuild" in held["by"] and held["since"] == NOW - 60
    assert _by(rows, "switch", f"{hold.GPU} hold")["state"] == f.ON
    speech = _by(rows, "switch", "SOHOT_SPEECH")
    assert speech["state"] == f.OFF and "deploy unit" in speech["by"]
    engine = _by(rows, "engine", "ds4")
    assert engine["state"] == f.OFF and f.NOTHING in engine["by"]
    assert _by(rows, "unit", "ds4")["state"] == f.ON_DEMAND
    assert _by(rows, "unit", "gateway")["state"] == f.ON
    assert _by(rows, "unit", "deploy")["state"] == f.OFF and "not loaded" in _by(rows, "unit", "deploy")["by"]
    assert _by(rows, "unit", "audit")["by"] == "not installed"
    assert not [r for r in rows if r["kind"] == "engine" and r["name"] == "gateway"]


def test_lanes_read_resident_served_by_a_node_or_on_demand(tmp_path):
    rows = _gather(tmp_path, None)
    assert _by(rows, "lane", "code")["state"] == f.ON and "resident" in _by(rows, "lane", "code")["by"]
    assert "served by node node-b" in _by(rows, "lane", "decide")["by"]
    image = _by(rows, "lane", "image")
    assert image["state"] == f.ON_DEMAND and "mflux" in image["by"]
    assert _by(rows, "switch", "holds")["state"] == f.UNKNOWN


def test_a_unit_that_last_exited_nonzero_is_broken_and_a_set_switch_is_on(tmp_path):
    root, agents, logs = _root(tmp_path / "x")
    (agents / f"{PREFIX}.deploy.plist").write_bytes(plistlib.dumps({"EnvironmentVariables": {"SOHOT_SPEECH": " On "}}))
    rows = _gather(tmp_path, None, root=root, agents=agents, logs=logs, listed={"ds4": (None, 1), "deploy": (None, 0)})
    assert _by(rows, "unit", "ds4")["state"] == f.BROKEN and "exit 1" in _by(rows, "unit", "ds4")["by"]
    assert _by(rows, "switch", "SOHOT_SPEECH")["state"] == f.ON


def test_the_tool_route_hook_reads_from_the_settings_file(tmp_path):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash|Read", "hooks": [
        {"type": "command", "command": "python scripts/tool-route-hook.py"}]}]}}), encoding="utf-8")
    assert f.hook_rows(s)[0]["state"] == f.ON
    s.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    assert f.hook_rows(s)[0]["state"] == f.OFF
    assert f.hook_rows(tmp_path / "none.json")[0]["state"] == f.OFF


def test_switches_are_found_in_the_code_not_listed():
    got = {var: fn for _, fn, var in f.switch_readers(paths.REPO)}
    assert got.get("SOHOT_SPEECH") == "speech_enabled"
    assert got.get("SOH_ROUTE") == "disabled"


def test_one_source_failing_leaves_the_others(tmp_path):
    (tmp_path / "bad").mkdir()
    rows = _gather(tmp_path, None, nodes_file=tmp_path / "bad" / "nodes.yaml", defaults=None, pinned=None,
                   listed={"ds4": (None, 0)})
    assert [r for r in rows if r["kind"] == "unit"]
    bad = tmp_path / "bad" / "nodes.yaml"
    bad.write_text("nodes: [{name: X}]", encoding="utf-8")
    rows = _gather(tmp_path / "y", None, nodes_file=bad)
    assert _by(rows, "node", "not read")["state"] == f.UNKNOWN
    assert _by(rows, "engine", "ds4")["state"] == f.OFF


def test_the_page_draws_each_state_with_what_decides_it(tmp_path):
    conn = ms.connect()
    try:
        hold.hold(conn, "owner: the test rebuild", now=NOW - 60)
        rows = _gather(tmp_path, conn)
    finally:
        conn.close()
    html = sv._features({"rows": rows, "as_of": NOW}, NOW)
    assert "data-kind='node' open" in html and "data-kind='engine' open" not in html
    assert "<span class='fs warn'>parked</span><span class='fn'>node-a</span>" in html
    assert "<span class='fs warn'>paused</span><span class='fn'>benchmarks hold</span>" in html
    assert "ds4: nothing to serve" in html
    assert "not read" in sv._features({"error": "boom"}, NOW)


def test_a_disabled_reader_reads_true_as_off():
    readers = [("harness.tool_route", "disabled", "SOH_ROUTE")]
    assert f.switches(paths.REPO, {}, readers)[0]["state"] == f.ON
    assert f.switches(paths.REPO, {"worker": {"SOH_ROUTE": "off"}}, readers)[0]["state"] == f.OFF


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/status_view.py:_FSTATE")
def test_every_feature_state_and_kind_has_its_drawing():
    assert set(sv._FSTATE) == set(f.STATES)
    assert [k for k, _ in sv._FKIND] == list(f.KINDS)


def test_a_new_switch_reader_is_found_without_a_restart(tmp_path):
    (tmp_path / "harness").mkdir()
    mod = tmp_path / "harness" / "knob_x.py"
    mod.write_text('X_ENV = "SOHOT_X"\n', encoding="utf-8")
    assert f.switch_readers(tmp_path) == ()
    mod.write_text('X_ENV = "SOHOT_X"\n\n\ndef on(environ=None):\n    return (environ or {}).get(X_ENV) == "1"\n',
                   encoding="utf-8")
    assert f.switch_readers(tmp_path) == (("harness.knob_x", "on", "SOHOT_X"),)


def test_an_unreadable_plist_or_log_is_unknown_not_absent(tmp_path):
    root, agents, logs = _root(tmp_path / "x")
    (agents / f"{PREFIX}.gateway.plist").write_text("not a plist", encoding="utf-8")
    (logs / "ds4.log").unlink()
    (logs / "ds4.log").mkdir()
    rows = _gather(tmp_path, None, root=root, agents=agents, logs=logs)
    assert _by(rows, "switch", "gateway unit environment")["state"] == f.UNKNOWN
    assert _by(rows, "engine", "ds4")["state"] == f.UNKNOWN
    (logs / "ds4.log").rmdir()
    rows = _gather(tmp_path / "y", None, root=root, agents=agents, logs=logs)
    assert not [r for r in rows if r["kind"] == "engine"]


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/status_page.py:_features:gather")
def test_the_only_process_the_feature_table_starts_is_a_launchctl_read(monkeypatch, tmp_path):
    import subprocess

    from harness import status_page as sp
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="PID\tStatus\tLabel\n", stderr="")
    monkeypatch.setattr(f.subprocess, "run", run)
    monkeypatch.setattr(f.sys, "platform", "darwin")
    got = sp._features(None, NOW, {"paused": False})
    assert calls == [["launchctl", "list"]]
    assert {r["kind"] for r in got["rows"]} >= {"unit", "switch", "hook"}
