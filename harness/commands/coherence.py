"""`soh coherence`: re-decide terminal verdicts the audit's terminal_reason_coherent names; read-only without --apply. #991."""
from __future__ import annotations

from pathlib import Path

from harness import coherence
from harness.commands.common import emit, err, note


def cmd_coherence(a) -> int:
    import sqlite3

    from harness import live_audit
    from harness import memory_store as ms
    db = Path(a.db) if a.db else ms.db_path()
    if not db.is_file():
        return err(f"coherence: no store at {db}")
    try:
        conn = ms.connect(db) if a.apply else live_audit.open_readonly(db)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        return err(f"coherence: {exc}")
    try:
        found = coherence.changes(conn)
        ids = coherence.apply(conn, found) if a.apply else []
        stops = _yield_stops(conn)
    except (sqlite3.Error, ms.IllegalTransition) as exc:
        return err(f"coherence: {exc}")
    finally:
        conn.close()
    for c in found:
        note(f"  {c['verdict_id']} {c['name']}: {c['why']}; {' / '.join(x or '-' for x in c['was'])} -> "
             f"{' / '.join(x or '-' for x in c['now']) if 'now' in c else c['skipped']}")
    note(f"{sum('now' in c for c in found)} of {len(found)} incoherent verdict(s) re-decided"
         + (f"; wrote {ids}" if a.apply else "; --apply writes them"))
    from harness import yield_stop
    note("yield stop points, in generated tokens:" + ("" if stops else " none"))
    for y in stops:
        note(f"  {yield_stop.line(y)}")
    emit(True, changes=[{k: v for k, v in c.items() if k != "excerpt"} for c in found], written=ids,
         yield_stops=stops)
    return 0


def _yield_stops(conn) -> list[dict]:
    """Each served lane-model's stop point and the GPU time it saves; [] when the store cannot say. #1127."""
    from harness import morning
    return morning.yield_stops(conn)
