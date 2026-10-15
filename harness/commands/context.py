"""`soh context`: tool-result tokens entering Claude's context, per tool or per day. #828."""
from __future__ import annotations

import time
from pathlib import Path

from harness.commands.common import emit, note


def _k(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n:,}"


def otel_rows(since, until: float) -> list[dict]:
    """The OTel tool_result rows in the shape `scan` gives: tool, tokens (bytes // 4), at, day."""
    from harness import ledger, otel
    conn = _read_conn()
    if conn is None:
        return []
    try:
        ev = otel.events(conn, since or 0.0, until, name="tool_result")
    finally:
        conn.close()
    return [{"tool": e["tool"] or "?", "tokens": int(e["result_bytes"] or 0) // 4, "at": e["at"],
             "day": ledger.day_of(e["at"], ledger._dt.timezone.utc)} for e in ev]


def _read_conn():
    """The live store read-only, or None when there is none."""
    from harness import ledger, memory_store as ms, store
    if store.backend() == store.POSTGRES:
        return ms.connect()
    path = ms.db_path()
    return ledger.open_ro(path) if path.exists() else None


def cmd_context(a) -> int:
    """Estimated tool-result tokens from Claude Code transcripts (chars / 4). #828."""
    from harness import context_report as cr

    now = time.time()
    try:
        since = cr.parse_when(a.since, now) if a.since else None
        until = cr.parse_when(a.until, now) if a.until else None
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    root = Path(a.root) if a.root else cr.default_root()
    source = getattr(a, "source", "transcripts")
    if source == "otel":
        raw = otel_rows(since, until if until is not None else now)
    else:
        raw = cr.scan(cr.transcripts(root, main_only=a.main_only, newer_than=since), since=since, until=until)
    if a.by == "category":
        from harness import otel
        label = otel.local_label if getattr(a, "label", "table") == "local" else None
        cats = otel.categorize((r["tool"] for r in raw), label=label)
        raw = [{**r, "category": cats[r["tool"]]} for r in raw]
    rows = cr.summarize(raw, by=a.by)
    gain = cr.rtk_gain()
    rtk = gain.get("summary") if isinstance(gain, dict) else None
    note("estimated tokens: " + ("OTel tool_result_size_bytes / 4" if source == "otel"
                                 else "tool_result characters / 4") + ", not a tokenizer count")
    note(f"{a.by:<28} {'calls':>7} {'tokens':>9} {'p50':>6} {'p95':>7} {'max':>7} {'share>2k':>8}")
    for r in rows:
        note(f"{str(r[a.by])[:28]:<28} {r['calls']:>7,} {_k(r['tokens']):>9} {r['p50']:>6,} "
             f"{r['p95']:>7,} {r['max']:>7,} {r['share_over_2k']:>8.0%}")
    if not rows:
        note(f"no tool results {'in otel_events' if source == 'otel' else f'under {root}'} in that window")
    if rtk:
        note(f"\nrtk gain (all time, rtk-rewritten commands only): {rtk.get('total_commands', 0):,} "
             f"commands, {rtk.get('total_saved', 0):,} tokens saved "
             f"({rtk.get('avg_savings_pct', 0):.1f}%)")
    out = {"estimate": "bytes/4" if source == "otel" else "chars/4", "source": source, "by": a.by, "root": str(root), "since": since,
           "until": until, "main_only": a.main_only, "rows": rows}
    if rtk:
        out["rtk"] = rtk
    emit(**out)
    return 0
