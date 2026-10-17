"""`soh load-log`: re-decide held llama.cpp load failures from the router's log, keeping each child's lines with its run. #953."""
from __future__ import annotations

from pathlib import Path

from harness import load_log
from harness.commands.common import emit, err, note


def cmd_load_log(a) -> int:
    import sqlite3

    from harness import live_audit
    from harness import memory_store as ms
    db = Path(a.db) if a.db else ms.db_path()
    if not db.is_file():
        return err(f"load-log: no store at {db}")
    try:
        conn = ms.connect(db) if a.apply else live_audit.open_readonly(db)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        return err(f"load-log: {exc}")
    try:
        found = load_log.changes(conn, a.log or None, a.runs or None)
        ids = load_log.apply(conn, found) if a.apply else []
    except OSError as exc:
        return err(f"load-log: {exc}")
    finally:
        conn.close()
    for c in found:
        note(f"  {c['verdict_id']} {c['name']}: {' / '.join(c['was'])} -> "
             f"{' / '.join(c['now']) + ' (' + load_log.source(c['excerpt']) + ')' if 'now' in c else c['skipped']}")
    note(f"{sum('now' in c for c in found)} held llama.cpp load failure(s) read from the router log"
         + (f"; wrote {ids}" if a.apply else "; --apply keeps the excerpts and writes the verdicts"))
    emit(True, changes=[{k: v for k, v in c.items() if k != "excerpt"} for c in found], written=ids)
    return 0
