"""`soh inventory time` across #1509: each blocked reason names its source, contention blocks, an owner hold stands apart. #1956."""
import datetime as dt

import pytest

from harness import inventory_time as it, ledger, paths
from harness import memory_store as ms
from harness.commands import inventory

UTC = dt.timezone.utc
H = 3600
#: The clock hour #1509 merged in; the window runs three hours either side of it.
F = int(it.CUTOVER_1509 // H) * H


def _other(conn) -> int:
    return conn.execute("INSERT INTO machines (fingerprint, hw_model, os, arch, first_seen, last_seen) "
                        "VALUES ('other/macOS/arm64', 'other', 'macOS', 'arm64', 0, 0)").lastrowid


def _act(conn, mid, at, crit, action):
    conn.execute("INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, dry_run) "
                 "VALUES (?, ?, ?, 'job 0001', ?, 0)", (at, mid, crit, action))


def _hold(conn, mid, kind, at, released):
    conn.execute("INSERT INTO holds (machine_id, kind, held_at, said, until, released_at) "
                 "VALUES (?, ?, ?, 'owner', NULL, ?)", (mid, kind, at, released))


@pytest.fixture
def spanning(tmp_path):
    """A clearance before #1509, a contention pause and a gpu hold after it; another machine's rows beside them."""
    home = paths.home()
    conn = ms.connect()
    mid = ms.remember_machine(conn)
    other = _other(conn)
    conn.execute("INSERT INTO day_clearances (machine_id, cleared_at, said, until) VALUES (?, ?, 'owner', ?)",
                 (mid, F - 3 * H + 60, F + 3 * H))
    _act(conn, mid, F - 2 * H + 60, "daytime_gpu", "notify")
    _act(conn, mid, F + 2 * H + 60, "contention", "pause")
    _hold(conn, mid, "gpu", F + H + 60, F + 3 * H - 60)
    _act(conn, other, F + H + 60, "contention", "pause")
    _hold(conn, other, "benchmarks", F - 3 * H, None)
    conn.commit()
    conn.close()
    return home


def _built(home, start, end):
    conn = ledger.open_ro(ms.db_path())
    try:
        src = it.gather(conn, home, end, since=start)
    finally:
        conn.close()
    return it.build(src, tz=UTC)


def _named(b) -> dict:
    return {r["reason"]: r for r in b["reasons"]}


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/inventory_time.py:gather:holds")
def test_a_window_spanning_1509_names_each_source_counts_contention_and_keeps_the_hold_apart(spanning):
    b = _built(spanning, F - 3 * H, F + 4 * H)["blocked"]
    got = _named(b)
    # The clearance ran to F + 3 h, but nothing read it after #1509: hours F - 3 h .. F only.
    assert got["day_clearance"]["hours"] == 4
    assert got["day_clearance"]["source"] == "day_clearances table" and got["day_clearance"]["to"] == it.CUTOVER_1509
    assert got["day_clearance"]["covers"] == 4
    assert got["day_limit"]["hours"] == 1 and "daytime_gpu" in got["day_limit"]["source"]
    assert got["contention"]["hours"] == 1, "another machine's contention pause was counted, or this one was not"
    assert got["contention"]["source"] == "watchdog_actions criterion contention"
    assert got["contention"]["from"] == it.CUTOVER_1509 and got["contention"]["covers"] == 4
    assert b["any"] == 5, "a hold hour counted as blocked"
    held = b[it.HELD]
    assert held["hours"] == 2 and held["by_kind"] == {"gpu": 2}, "another machine's hold, or none, was counted"
    assert held["source"] == "holds table" and held["covers"] == 7


def test_after_1509_the_dead_sources_read_as_unwritten_not_as_nothing_cleared(spanning, capsys):
    L = _built(spanning, F + H, F + 4 * H)
    got = _named(L["blocked"])
    assert got["day_clearance"]["hours"] is None and got["day_limit"]["hours"] is None
    assert got["contention"]["hours"] == 1
    inventory.show(L)
    out = capsys.readouterr().out
    clear = next(line for line in out.splitlines() if line.strip().startswith("day_clearance"))
    assert "--" in clear and "no writer in this window" in clear and "#1509" in clear
    assert "owner took the machine back (not blocked): 2 hour(s)" in out
    assert "[holds table, written from" in out


def test_before_1509_the_report_names_the_successor_sources_as_unwritten(spanning, capsys):
    L = _built(spanning, F - 3 * H, F - H)
    got = _named(L["blocked"])
    assert got["day_clearance"]["hours"] == 2 and got["contention"]["hours"] is None
    inventory.show(L)
    out = capsys.readouterr().out
    line = next(x for x in out.splitlines() if x.strip().startswith("contention"))
    assert "--" in line and "watchdog_actions criterion contention: no writer in this window" in line
