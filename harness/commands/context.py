"""`soh context`: tool-result tokens entering Claude's context, per tool or per day. #828."""
from __future__ import annotations

import time
from pathlib import Path

from harness.commands.common import emit, note


def _k(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n:,}"


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
    files = cr.transcripts(root, main_only=a.main_only, newer_than=since)
    rows = cr.summarize(cr.scan(files, since=since, until=until), by=a.by)
    gain = cr.rtk_gain()
    rtk = gain.get("summary") if isinstance(gain, dict) else None
    note("estimated tokens: tool_result characters / 4, not a tokenizer count")
    note(f"{a.by:<28} {'calls':>7} {'tokens':>9} {'p50':>6} {'p95':>7} {'max':>7} {'share>2k':>8}")
    for r in rows:
        note(f"{str(r[a.by])[:28]:<28} {r['calls']:>7,} {_k(r['tokens']):>9} {r['p50']:>6,} "
             f"{r['p95']:>7,} {r['max']:>7,} {r['share_over_2k']:>8.0%}")
    if not rows:
        note(f"no tool results under {root} in that window")
    if rtk:
        note(f"\nrtk gain (all time, rtk-rewritten commands only): {rtk.get('total_commands', 0):,} "
             f"commands, {rtk.get('total_saved', 0):,} tokens saved "
             f"({rtk.get('avg_savings_pct', 0):.1f}%)")
    out = {"estimate": "chars/4", "by": a.by, "root": str(root), "since": since,
           "until": until, "main_only": a.main_only, "rows": rows}
    if rtk:
        out["rtk"] = rtk
    emit(**out)
    return 0
