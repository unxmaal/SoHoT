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
        conn = ms.connect(db) if a.apply and not a.idle else live_audit.open_readonly(db)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        return err(f"load-log: {exc}")
    if a.idle:
        try:
            return _idle(conn, a.log or None)
        finally:
            conn.close()
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


def _idle(conn, logs=None) -> int:
    """Cold-load seconds per model, and what each serve_idle_unload limit in range costs each served model. #1157."""
    import time

    from harness import idle_unload, knobs
    loads: dict = {}
    for log in [Path(p) for p in logs] if logs else load_log.router_logs():
        if log.is_file():
            with log.open(encoding="utf-8", errors="replace") as f:
                for model, got in idle_unload.load_seconds(f).items():
                    loads.setdefault(model, []).extend(got)
    now = time.time()
    since = now - idle_unload.WINDOW_DAYS * 86400
    used = idle_unload.uses(conn, since)
    limits = sorted({*knobs.KNOBS["serve_idle_unload_day_s"].values, *knobs.KNOBS["serve_idle_unload_s"].values})
    loaded = {m: idle_unload.summary(v) for m, v in sorted(loads.items(), key=lambda kv: -len(kv[1]))}
    note("cold load, spawn to `model loaded` (router log):")
    for m, s in loaded.items():
        note(f"  {m}: {s['n']} loads, median {s['median_s']}s, p90 {s['p90_s']}s, max {s['max_s']}s")
    costs = {m: {str(int(t)): idle_unload.cost(spans, t, idle_unload.WINDOW_DAYS) for t in limits}
             for m, spans in sorted(used.items(), key=lambda kv: -len(kv[1]))}
    note(f"requests and cost per limit over {idle_unload.WINDOW_DAYS} days (loads/day, idle-but-loaded h/day):")
    for m, by in costs.items():
        note(f"  {m} ({len(used[m])} requests): "
             + "; ".join(f"{t}s {c['loads_per_day']}/{c['idle_h_per_day']}" for t, c in by.items()))
    emit(True, loads=loaded, costs=costs, requests={m: len(v) for m, v in used.items()})
    return 0
