"""`soh sweep-check`: tonight's discovery sweep from launchd and its heartbeat; --notify records and notifies. #1062."""
from __future__ import annotations

from harness.commands.common import emit, note


def cmd_sweep_check(a) -> int:
    from harness import sweep_check
    r = sweep_check.check()
    note(f"{r['verdict']}: {r['line']}")
    if a.notify and r["verdict"] != sweep_check.UNSUPPORTED:
        from harness import memory_store as ms
        conn = ms.connect()
        try:
            r["recorded"] = sweep_check.record(conn, r)
        finally:
            conn.close()
        note(r["recorded"]["outcome"])
    emit(r["verdict"] in sweep_check.QUIET, **r)
    return 0
