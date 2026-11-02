"""`soh runtimes`: newer releases of pinned runtimes, their sandboxed trials and verdicts. #1474."""
from __future__ import annotations

from harness.commands.common import emit, note


def cmd_runtimes(a) -> int:
    from harness import memory_store as ms, runtime_trials as rtt
    conn = ms.connect()
    try:
        watched = rtt.watch(conn) if (a.watch or a.trial) else []
        tried = rtt.trial(conn) if a.trial else []
        rows = [dict(r) for r in conn.execute(
            "SELECT runtime, version, pinned, outcome, detail, lane, seen_at, decided_at FROM runtime_trials "
            "ORDER BY id DESC LIMIT ?", (a.limit,)).fetchall()]
    finally:
        conn.close()
    if watched or tried:
        for text in rtt.lines(watched, tried):
            note(text)
    note(f"\n{len(rows)} runtime release(s) recorded")
    for r in rows:
        note(f"  {rtt.line(r)}")
    emit(not any(t["outcome"] in rtt.PUSHED for t in tried), watched=watched, tried=tried, trials=rows)
    return 0
