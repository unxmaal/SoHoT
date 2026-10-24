"""A stale MCP server's clients are named, since Claude Code refetches tools/list only when their stream ends (#1166)."""
import os
import shutil
import signal
import socket
import sqlite3
import sys
import time

import pytest

from harness import mcp_peers, mcp_server, morning
from harness import watchdog as wd
from harness.commands import morning as morning_cmd

from tests.test_mcp_orphans_1155 import ARGS, PY, P, Unit, _hold, _port, _start
from tests.test_watchdog import NIGHT

pytest.importorskip("mcp")

CLAUDE = "claude --resume ghscavenge"
# lsof -nP -iTCP:8899 -sTCP:ESTABLISHED -Fpn on the Studio, 2026-10-24: the orphan 13283 holds one session
LSOF = "\n".join([
    "p13283", "f8", "n127.0.0.1:8899->127.0.0.1:61599",
    "p54868", "f23", "n127.0.0.1:61599->127.0.0.1:8899",
    "p95969", "f7", "n127.0.0.1:8899->127.0.0.1:54934", "f9", "n203.0.113.5:8899->203.0.113.20:50000",
    "p777", "f4", "n127.0.0.1:54934->127.0.0.1:8899",
]) + "\n"
PROCS = [P(95969, 1, f"{PY} {ARGS}"), P(13283, 1, f"{PY} {ARGS}", elapsed=88659),
         P(54868, 1, CLAUDE, elapsed=80000), P(777, 1, "claude")]


def test_each_server_is_mapped_to_the_processes_at_the_other_end_of_its_connections():
    held = mcp_peers.clients(LSOF, 8899)
    assert held == {13283: [54868], 95969: [777, "203.0.113.20:50000"]}
    assert mcp_peers.clients(LSOF, 9000) == {} and mcp_peers.clients("", 8899) == {}
    assert mcp_peers.describe(54868, PROCS) == f"pid 54868 (up 22h) {CLAUDE}"
    assert mcp_peers.describe(4, PROCS) == "pid 4" and mcp_peers.describe("198.51.100.2:5", PROCS) == "198.51.100.2:5"


def _stale(tmp_path, connections):
    probes = Unit(tmp_path, PROCS, 95969)
    probes.connections = connections
    world = wd.observe(probes, None, NIGHT)
    found, _ = wd.judge(world)
    return next(f for f in found if f.criterion == "stale_mcp")


def test_the_watchdog_names_the_sessions_still_on_a_stale_server_and_how_they_refresh(tmp_path):
    f = _stale(tmp_path, LSOF)
    assert f.subject.key == "mcp pid 13283"
    assert f.evidence["clients"] == [f"pid 54868 (up 22h) {CLAUDE}"]
    assert "refetches tools/list" in f.evidence["remedy"] and f.evidence["stop"] == "kill -INT 13283"


def test_without_lsof_the_clients_are_a_stated_gap_not_an_empty_list(tmp_path):
    assert "lsof cannot be asked" in _stale(tmp_path, None).evidence["clients"]


class Probes:
    def __init__(self, listing):
        self.listing = listing

    def processes(self):
        return PROCS

    def mcp_connections(self, port):
        return self.listing


def test_a_new_server_names_each_stale_server_s_client_at_start():
    lines = mcp_server.stale_report(8899, 95969, probes=Probes(LSOF))
    assert lines[0].startswith("mcp   STALE server pid 13283")
    assert lines[1] == f"mcp     its client pid 54868 (up 22h) {CLAUDE}"
    assert lines[2].startswith("mcp   stop them with: kill -INT 13283; stopping it")
    assert len(mcp_server.stale_report(8899, 95969, probes=Probes(None))) == 2


def test_soh_morning_carries_the_clients_into_its_needs_and_its_watchdog_lines():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE watchdog_actions (id INTEGER PRIMARY KEY, at REAL, criterion TEXT, subject TEXT, "
                 "action TEXT, escalated INTEGER, dry_run INTEGER, evidence TEXT, outcome TEXT)")
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, evidence, outcome) "
                 "VALUES (?, 'stale_mcp', 'mcp pid 13283', 'file', 1, 0, ?, 'not filed')",
                 (NIGHT, '{"clients": ["pid 54868 (up 22h) claude --resume ghscavenge"]}'))
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, evidence, outcome) "
                 "VALUES (?, 'overrun', 'eval pgid 2', 'stop', 1, 0, 'not json', 'group term')", (NIGHT + 1,))
    rows = morning.watchdog(conn, NIGHT - 1)
    assert [r["clients"] for r in rows] == [["pid 54868 (up 22h) claude --resume ghscavenge"], []]
    needs = morning.needs({"watchdog": rows, "ci": {}, "deploy": {}, "sweep": {}, "ledger": None, "stale": []})
    assert any("its clients keep the old tool list: pid 54868" in n for n in needs)


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("lsof"), reason="lsof names the peers")
def test_a_real_restart_names_this_process_as_the_old_server_s_client(tmp_path):
    port = _port()
    old = _start(tmp_path, port, "--shutdown-grace", "600")
    client = _hold(port)
    new = None
    try:
        old.send_signal(signal.SIGTERM)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(0.1)
        new = _start(tmp_path, port, name="b")
        log = (tmp_path / "b.log").read_text(encoding="utf-8")
        assert f"STALE server pid {old.pid}" in log
        assert f"its client pid {os.getpid()} " in log
    finally:
        for p in (old, new):
            if p is not None:
                p.kill()
        client.close()
