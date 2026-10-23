"""`soh delegated`: what became of each local_complete / local_decide answer. #829."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, note


def _rate(x) -> str:
    return "--" if x is None else f"{x:.0%}"


def cmd_delegated(a) -> int:
    from harness import delegations, usage
    from harness import memory_store as ms

    if getattr(a, "close", False):
        return _close(a)
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
    conn = ms.connect()
    try:
        if not a.report:
            try:
                got = delegations.outcome(conn, a.call_id, a.outcome, a.why)
            except (ValueError, delegations.UnknownCall) as exc:
                note(str(exc))
                emit(False, error=str(exc))
                return 1
            note(f"{got['call_id']}: {got['outcome']}"
                 + (f" ({got['note']})" if got["note"] else ""))
            emit(**got)
            return 0
        rows = delegations.report(conn, since)
    finally:
        conn.close()
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
    emit(report=rows, since=a.since)
    return 0


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
