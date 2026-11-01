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


def _carried(a, root: Path, source: str, since, until) -> int:
    """`soh context --carried`: what tool output costs over a session, not only when it arrives."""
    from harness import context_report as cr
    if source != "transcripts" or a.by == "day":
        why = "--carried reads transcripts per stream: it takes --by tool or category and --source transcripts"
        note(why)
        emit(False, error=why)
        return 2
    got = cr.carried(root, since=since, until=until, main_only=a.main_only)
    rows = got["tools"]
    if a.by == "category":
        from harness import otel
        label = otel.local_label if getattr(a, "label", "table") == "local" else None
        cats = otel.categorize((r["tool"] for r in rows), label=label)
        merged: dict = {}
        for r in rows:
            m = merged.setdefault(cats[r["tool"]], {"category": cats[r["tool"]], "results": 0, "entered": 0, "carried": 0})
            for k in ("results", "entered", "carried"):
                m[k] += r[k]
        total = got["input"]
        rows = sorted(({**m, "share": round(m["carried"] / total, 4) if total else 0.0} for m in merged.values()),
                      key=lambda r: (-r["carried"], r["category"]))
    note("estimated tokens: characters / 4; carried = a result's tokens times the later API calls of its stream "
         "until a compaction")
    note(f"{got['input']:,} input tokens over {got['api_calls']:,} API calls in {got['streams']:,} streams; "
         f"tool output carried {got['carried']:,} "
         f"({got['carried'] / got['input'] if got['input'] else 0:.1%}), {got['compactions']} compactions")
    note(f"{a.by:<28} {'results':>8} {'entered':>9} {'carried':>9} {'share':>6}")
    for r in rows:
        note(f"{str(r[a.by])[:28]:<28} {r['results']:>8,} {_k(r['entered']):>9} {_k(r['carried']):>9} "
             f"{r['share']:>6.1%}")
    emit(estimate="chars/4", source=source, by=a.by, root=str(root), since=since, until=until,
         main_only=a.main_only, input=got["input"], api_calls=got["api_calls"], streams=got["streams"],
         compactions=got["compactions"], carried=got["carried"], rows=rows)
    return 0


def _by_class(a, root: Path, since, until) -> int:
    """`soh context --carried --by class`: which output Claude carries and whether it used it. #1333."""
    from harness import context_class as cc
    referenced = getattr(a, "referenced", False)
    got = cc.carried(root, since=since, until=until, main_only=a.main_only, referenced=referenced)
    total = got["input"]
    note("estimated tokens: characters / 4; carried = tokens times the later API calls of the stream "
         "until a compaction; >=1k = carried by results of at least 1,000 tokens")
    note(f"{total:,} input tokens over {got['api_calls']:,} API calls in {got['streams']:,} streams; "
         f"tool output carried {got['carried']:,} ({got['carried'] / total if total else 0:.1%}), "
         f"Claude's own blocks {got['own_carried']:,}, {got['compactions']} compactions")
    for kind, title in (("output", "class"), ("own", "Claude's own blocks")):
        note(f"\n{title:<36} {'results':>8} {'entered':>9} {'carried':>9} {'share':>6} {'>=1k':>9}")
        for r in (r for r in got["rows"] if r["kind"] == kind):
            note(f"{r['class'][:36]:<36} {r['results']:>8,} {_k(r['entered']):>9} {_k(r['carried']):>9} "
                 f"{r['share']:>6.1%} {_k(r['carried_1k']):>9}")
    reads = got["reads"]
    note(f"\nReads >=1k: {reads['over_1k']:,}, never edited later {reads['never_edited']:,}; carried by kind: "
         + ", ".join(f"{k} {_k(v)}" for k, v in sorted(reads["never_edited_carried_1k"].items(),
                                                        key=lambda kv: -kv[1])))
    if referenced:
        kb = got["kb"]
        note(f"KB searches >=1k: {kb['searches']:,} showing {kb['hits']:,} hits; referenced later "
             f"{kb['referenced']:,} ({kb['referenced'] / kb['hits'] if kb['hits'] else 0:.1%}); "
             f"{kb['unreferenced_searches']:,} searches with none; "
             f"{kb['at_6_or_later'] / kb['referenced'] if kb['referenced'] else 0:.0%} of referenced at position 6+")
    emit(estimate="chars/4", source="transcripts", by="class", root=str(root), since=since, until=until,
         main_only=a.main_only, **got)
    return 0


def _p(p: float) -> str:
    return f"{p:.2g}" if p < 0.001 else f"{p:.3f}"


def _mistakes(a, root: Path, since, until) -> int:
    """`soh context --mistakes`: KB mistakes after a compaction and per context band, against messages. #1381."""
    import os
    from harness import context_mistakes as cm
    source = a.kb or os.environ.get("SOH_MCM_URL", "")
    if not source:
        why = "--mistakes needs --kb: the mcm-engine MCP URL or a file of its scroll_entries pages (or $SOH_MCM_URL)"
        note(why)
        emit(False, error=why)
        return 2
    try:
        rows = cm.load_rows(source)
    except (OSError, ValueError) as exc:
        why = f"cannot read the KB rows: {type(exc).__name__}"
        note(why)
        emit(False, error=why)
        return 1
    got = cm.measure(root, rows, since=since, until=until)
    note("messages: assistant API messages of interactive main transcripts; mistakes: KB negative and error rows "
         f"joined to their main-stream call within {cm.MATCH_S} s; control: add_knowledge and add_rule calls")
    note(f"{got['messages']:,} messages in {got['sessions']} sessions, {got['compactions']} compactions; "
         f"{got['kb_rows']} KB rows, {got['joined']} joined, left out "
         + (", ".join(f"{k} {v}" for k, v in sorted(got["left_out"].items())) or "none")
         + f"; control {got['control']}")
    note("p: one-sided exact upper tails; binomial pools all messages, session puts each event over its own "
         f"session's messages; {got['tests']} tests, Bonferroni 0.05 = {0.05 / got['tests']:.2g}")
    for title, key, rows_ in (("after compaction", "window", got["windows"]), ("context band", "band", got["bands"])):
        note(f"\n{title:<16} {'class':<9} {'msgs':>7} {'share':>6} {'events':>8} {'share':>6} {'lift':>5} "
             f"{'p binom':>8} {'p sess':>8}")
        for r in rows_:
            label = f"<= {r[key]}" if key == "window" else r[key]
            lift = f"{r['lift']:.2f}" if r["lift"] is not None else "-"
            note(f"{label:<16} {r['class']:<9} {r['messages']:>7,} {r['message_share']:>6.1%} "
                 f"{r['events']:>3}/{r['events_total']:<4} {r['event_share']:>6.1%} {lift:>5} "
                 f"{_p(r['p_binomial']):>8} {_p(r['p_session']):>8}")
    emit(source="url" if source.startswith(("http://", "https://")) else "file", root=str(root), since=since,
         until=until, window_sizes=list(cm.WINDOWS), band_edges=list(cm.BANDS), match_s=cm.MATCH_S, **got)
    return 0


def cmd_context(a) -> int:
    """Estimated tool-result tokens from Claude Code transcripts (chars / 4). #828."""
    from harness import context_report as cr

    now = time.time()
    try:
        mistakes = getattr(a, "mistakes", False)
        when = a.since if a.since is not None else ("" if mistakes else "7d")
        since = cr.parse_when(when, now) if when else None
        until = cr.parse_when(a.until, now) if a.until else None
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    root = Path(a.root) if a.root else cr.default_root()
    source = getattr(a, "source", "transcripts")
    if mistakes:
        return _mistakes(a, root, since, until)
    if getattr(a, "carried", False):
        if a.by == "class" and source == "transcripts":
            return _by_class(a, root, since, until)
        return _carried(a, root, source, since, until)
    if a.by == "class":
        why = "--by class measures carried context: add --carried"
        note(why)
        emit(False, error=why)
        return 2
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
