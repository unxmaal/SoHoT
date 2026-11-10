"""#1714: a dropped usage row warns in the audit and never fails an install; the writer outlasts a store blip."""
import threading
import time

from harness import cli, live_audit, usage
from harness import memory_store as ms
from tests.test_live_audit import _checks, config, live  # noqa: F401
from tests.test_usage import payload, response


def _drop(n=1):
    conn = ms.connect()
    try:
        usage.record_dropped(conn, n)
    finally:
        conn.close()


def _failing_rates():
    conn = ms.connect()
    now = time.time()
    for i in range(live_audit.MIN_REQUESTS):
        conn.execute("INSERT INTO gateway_requests (at, alias, lane, error_class) VALUES (?, 'sohot-code', 'code', ?)",
                     (now - i, "APIError" if i % 2 else ""))
    conn.commit()
    conn.close()


def test_one_dropped_row_and_sound_rates_pass_gateway_errors_with_a_warning(live, capsys):
    _drop()
    got = live_audit.audit(live)
    check = _checks(got)["gateway_errors"]
    assert got["ok"] and check["ok"] and check["warn"]
    assert "1 gateway usage row(s) were dropped" in check["detail"]
    assert cli.main(["audit"]) == 0
    out = capsys.readouterr().out
    assert "warn gateway_errors: 1 gateway usage row(s) were dropped" in out and out.rstrip().endswith("OK")


def test_failing_rates_still_fail_and_say_the_sample_was_incomplete(live):
    _drop()
    _failing_rates()
    check = _checks(live_audit.audit(live))["gateway_errors"]
    assert not check["ok"] and "sohot-code" in check["detail"] and "dropped" in check["detail"]


class _Lost:
    """A connection whose server went away: every statement raises."""

    def execute(self, *a, **k):
        raise ConnectionError("the connection is lost")

    def close(self):
        pass


def _row():
    return usage.row(payload(), response())


def _count():
    conn = ms.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM gateway_requests").fetchone()[0], usage.dropped_since(conn, 0.0)
    finally:
        conn.close()


def test_the_writer_reconnects_after_a_lost_connection_and_drops_nothing():
    opened = []

    def connect():
        opened.append(1)
        return _Lost() if len(opened) == 1 else ms.connect()
    logged = []
    w = usage.Writer(connect=connect, flush_s=0.01, log=logged.append).start()
    for _ in range(3):
        w.put(_row())
    deadline = time.monotonic() + 10
    while _count()[0] < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    w.close()
    assert _count() == (3, 0) and w.dropped == 0 and len(opened) == 2, logged
    assert not any("dropping" in m for m in logged)


def test_a_store_down_past_the_retry_window_drops_and_records_the_batch():
    up = threading.Event()

    def connect():
        if not up.is_set():
            raise ConnectionError("connection refused")
        return ms.connect()
    w = usage.Writer(connect=connect, flush_s=0.01, retry_s=0.05, log=lambda m: None).start()
    w.put(_row())
    deadline = time.monotonic() + 10
    while not w.dropped and time.monotonic() < deadline:
        time.sleep(0.01)
    up.set()
    w.close()
    assert w.dropped == 1 and _count() == (0, 1)
