"""`soh usage`: real use through the gateway. #481."""
from __future__ import annotations

from harness.commands.common import emit, note


def _rate(x) -> str:
    return "--" if x is None else f"{x:.1%}"


def _secs(x) -> str:
    return "--" if x is None else f"{x:.2f}s"


def cmd_usage(a) -> int:
    """What real use through the gateway looked like, per alias, and across switches. #481."""
    from harness import usage
    from harness import memory_store as ms

    conn = ms.connect()
    try:
        if a.text:
            usage.set_text(conn, a.text == "on")
            note(f"text samples are {a.text}: the gateway "
                 f"{'keeps' if a.text == 'on' else 'keeps no'} prompt and completion "
                 f"text (newest {usage.SAMPLE_ROWS}, {usage.SAMPLE_CHARS} chars each)")
            emit(text=a.text == "on")
            return 0
        try:
            since = usage.parse_since(a.since)
        except ValueError as exc:
            note(str(exc))
            emit(False, error=str(exc))
            return 2
        lane = (a.lane or "").strip().lower() or None
        now = usage.time.time()
        rows = usage.summary(conn, lane=lane, since=since, now=now)
        comps = usage.around_switches(conn, lane=lane, since=since, now=now)
        warnings = usage.regressions(comps)
        text_on = usage.text_enabled(conn)
    finally:
        conn.close()
    if not rows:
        note(f"no requests through the gateway in the last {a.since}"
             f"{f' on sohot-{lane}' if lane else ''}")
    else:
        note(f"{'alias':<16} {'served':<36} {'reqs':>5} {'tokens in/out':>15} "
             f"{'TTFT p50/p95':>14} {'errors':>7} {'bad calls':>9}")
        for r in rows:
            note(f"{r['alias'][:16]:<16} {r['served'][:36]:<36} {r['requests']:>5} "
                 f"{r['prompt_tokens']:>7}/{r['completion_tokens']:<7} "
                 f"{_secs(r['ttft_p50']):>6}/{_secs(r['ttft_p95']):<7} "
                 f"{_rate(r['error_rate']):>7} {_rate(r['invalid_rate']):>9}")
    for c in comps:
        sw, b, af = c["switch"], c["before"], c["after"]
        note(f"\nswitch #{sw['id']} sohot-{sw['lane']}: {sw['old_spec']} -> {sw['new_spec']}")
        for side, s in (("before", b), ("after", af)):
            note(f"  {side:<6} {s['requests']:>5} reqs  errors {_rate(s['error_rate'])}  "
                 f"bad calls {_rate(s['invalid_rate'])}  TTFT p50 {_secs(s['ttft_p50'])}")
    for w in warnings:
        note(f"WARNING {w}")
    if text_on:
        note("text samples are ON (`soh usage --text off` stops keeping them)")
    emit(summary=rows, switches=comps, warnings=warnings, text=text_on)
    return 0
