"""A stale too-big backlog is an inventory until a loop's requeue has run over it; one that survives fails. #904."""
import argparse

import pytest

from harness import heartbeat, live_audit
from harness import memory_store as ms
from harness.commands import loop as loop_cmd

GIB = 1024 ** 3


def _decline(conn, name, ceiling_gb):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights",
                            registry=ms.HUGGINGFACE, lane="code"))
    ms.decide(conn, name, "declined", tier=ms.INSPECT, reason="machine", until="ceiling_gb:>398.1",
              detail="too-big: over the 22 GiB ceiling", size_bytes=int(398.1 * GIB), ceiling_gb=ceiling_gb)


def _decided(conn, name):
    return conn.execute("SELECT v.decided_at FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.name = ?", (name,)).fetchone()[0]


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def test_a_backlog_no_requeue_has_seen_warns_and_does_not_fail(store):
    _decline(store, "org/stale", 22.0)
    failed, warned = live_audit._too_big_ceiling_current(store, 66.0, None)
    assert failed == []
    assert len(warned) == 1 and "org/stale (22 GiB)" in warned[0] and "await" in warned[0]


def test_a_backlog_decided_after_the_last_requeue_still_only_warns(store):
    _decline(store, "org/stale", 22.0)
    failed, warned = live_audit._too_big_ceiling_current(store, 66.0, _decided(store, "org/stale") - 60)
    assert failed == [] and len(warned) == 1


def test_a_backlog_older_than_the_last_requeue_fails(store):
    _decline(store, "org/stale", 22.0)
    failed, warned = live_audit._too_big_ceiling_current(store, 66.0, _decided(store, "org/stale") + 60)
    assert len(failed) == 1 and "survived" in failed[0] and warned == []


def test_the_audit_reports_the_fresh_backlog_as_a_passing_warning(tmp_path):
    conn = ms.connect()
    try:
        _decline(conn, "org/stale", 1.0)
    finally:
        conn.close()
    heartbeat.start()
    heartbeat.finish(0)
    got = live_audit.audit(ms.db_path())
    check = {c["name"]: c for c in got["checks"]}["too_big_ceiling_current"]
    assert check["ok"] and check["warn"] and "org/stale" in check["detail"]
    assert "warn too_big_ceiling_current" in live_audit.report_text(got)


def test_the_audit_fails_once_the_loop_requeue_ran_and_the_row_survived(tmp_path):
    conn = ms.connect()
    try:
        _decline(conn, "org/stale", 1.0)
        after = _decided(conn, "org/stale") + 60
    finally:
        conn.close()
    heartbeat.start()
    heartbeat.mark(heartbeat.REOPENED_TOO_BIG, after)
    heartbeat.finish(0)
    check = {c["name"]: c for c in live_audit.audit(ms.db_path())["checks"]}["too_big_ceiling_current"]
    assert not check["ok"] and not check["warn"] and "survived" in check["detail"]


def test_the_loop_marks_its_requeue_and_the_mark_outlives_the_next_loop_start(monkeypatch):
    heartbeat.start()
    monkeypatch.setattr(heartbeat, "clock", lambda: 1234.0)
    monkeypatch.setattr(ms, "requeue_stale_too_big", lambda conn: [])
    loop_cmd._reopen_stale_too_big()
    heartbeat.finish(0)
    assert heartbeat.reopened_too_big() == 1234.0
    heartbeat.start()
    assert heartbeat.reopened_too_big() == 1234.0


def test_a_dry_run_loop_leaves_no_requeue_mark(monkeypatch):
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", lambda sub: 0)
    heartbeat.start()
    loop_cmd._run_loop_held(argparse.Namespace(run=False, lane=""))
    heartbeat.finish(0)
    assert heartbeat.reopened_too_big() is None
