"""`soh delegated`: what became of each local_complete / local_decide answer. #829."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, note


def _rate(x) -> str:
    return "--" if x is None else f"{x:.0%}"


def _secs(x) -> str:
    return "--" if x is None else f"{x:.1f}"


def cmd_delegated(a) -> int:
    from harness import delegations, usage

    if getattr(a, "close", False):
        return _close(a)
    if a.call_id and not a.outcome and not a.report:
        return _show(a.call_id)
    if not a.report and not (a.call_id and a.outcome):
        note("give a call id and used|edited|discarded, or --report, or --close")
        emit(False, error="call id and outcome, or --report, or --close")
        return 2
    try:
        since = usage.parse_since(a.since)
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    import contextlib

    from harness.commands.common import lent_store
    held = contextlib.ExitStack()
    # An outcome goes where the delegation went, the live store as it stands from any checkout. #1717.
    conn = held.enter_context(lent_store() if a.report else delegations.ledger())
    try:
        if not a.report:
            if conn is None:
                why = "not recorded: this checkout cannot write the live store (see the line above)"
                note(why)
                emit(False, error=why)
                return 1
            try:
                got = delegations.outcome(conn, a.call_id, a.outcome, a.why or getattr(a, "said", ""))
            except (ValueError, delegations.UnknownCall) as exc:
                note(str(exc))
                emit(False, error=str(exc))
                return 1
            note(f"{got['call_id']}: {got['outcome']}"
                 + (f" ({got['note']})" if got["note"] else ""))
            emit(**got)
            return 0
        rows = delegations.report(conn, since)
        from harness import serve_lease
        waits = serve_lease.waits(conn, since)
    finally:
        held.close()
    if not rows:
        note(f"no delegations in the last {a.since}")
    else:
        note(f"{'lane':<10} {'calls':>5} {'recorded':>8} {'used':>5} {'edited':>6} "
             f"{'discarded':>9} {'accepted':>8} {'rejected':>8} {'unknown':>7} {'pending':>7} {'median s':>8}")
        for r in rows:
            med = "--" if r["median_seconds"] is None else f"{r['median_seconds']:.1f}"
            note(f"{r['lane']:<10} {r['count']:>5} {_rate(r['recorded_rate']):>8} "
                 f"{_rate(r['used_rate']):>5} {_rate(r['edited_rate']):>6} "
                 f"{_rate(r['discarded_rate']):>9} {r['accepted']:>8} {r['rejected']:>8} "
                 f"{r['unknown']:>7} {r['pending']:>7} {med:>8}")
    if waits:
        note(f"\nwaits on a held machine and whole latency (#1556)\n{'lane':<10} {'waits':>5} {'refused':>7} "
             f"{'cut':>4} {'beside':>6} {'median s':>8} {'max s':>7} {'p95 s':>7}  target")
        for w in waits:
            target = ("" if w["target_s"] is None else
                      f"{'OVER ' if w['over_target'] else ''}{w['target_s']:g}s")
            note(f"{w['lane']:<10} {w['waits']:>5} {w['refused']:>7} {w['cut']:>4} {w['beside']:>6} "
                 f"{_secs(w['median_wait_s']):>8} {_secs(w['max_wait_s']):>7} {_secs(w['p95_s']):>7}  {target}")
    emit(report=rows, waits=waits, since=a.since)
    return 0


def _show(call_id: str) -> int:
    """`soh delegated CALL_ID`: the delegation and the gateway_requests rows that carry its id, read-only. #1721."""
    from harness import delegations
    from harness.commands.common import lent_store
    with lent_store() as conn:
        got = delegations.rows(conn, call_id)
    d, reqs = got["delegation"], got["requests"]
    if d is None:
        note(f"no delegation has call id {call_id!r}")
    else:
        note(f"{call_id}: lane {d['lane']}, {d['prompt_tokens'] or 0} in / {d['completion_tokens'] or 0} out, "
             f"outcome {d['outcome'] or 'pending'}")
    note(f"{len(reqs)} gateway request(s) carry it" + (":" if reqs else ""))
    for r in reqs:
        note(f"  {r['at']:.0f} {r['alias'] or '-':<16} {r['client'] or '-':<14} {r['purpose'] or '-':<8} "
             f"{r['prompt_tokens'] or 0:>7} in {r['completion_tokens'] or 0:>6} out"
             + (f"  {r['error_class']}" if r["error_class"] else ""))
    emit(d is not None, **got)
    return 0 if d is not None else 1


def _close(a) -> int:
    """Close pending outcomes from the callers' transcripts; the delegations unit runs this hourly. #1158."""
    from harness import context_report as cr, delegations
    from harness import memory_store as ms

    root = cr.default_root() if not a.root else Path(a.root).expanduser()
    conn = ms.connect()
    try:
        got = delegations.close(conn, root=root, expiry_h=a.expiry_h)
    finally:
        conn.close()
    note(f"closed {got['accepted']} accepted, {got['rejected']} rejected, {got['unknown']} unknown; "
         f"{got['pending']} still pending ({got['transcripts']} transcripts read)")
    emit(**got)
    return 0
