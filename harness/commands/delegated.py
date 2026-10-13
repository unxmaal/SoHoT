"""`soh delegated`: what became of each local_complete / local_decide answer. #829."""
from __future__ import annotations

from harness.commands.common import emit, note


def _rate(x) -> str:
    return "--" if x is None else f"{x:.0%}"


def cmd_delegated(a) -> int:
    from harness import delegations, usage
    from harness import memory_store as ms

    if not a.report and not (a.call_id and a.outcome):
        note("give a call id and used|edited|discarded, or --report")
        emit(False, error="call id and outcome, or --report")
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
             f"{'discarded':>9} {'median s':>8}")
        for r in rows:
            med = "--" if r["median_seconds"] is None else f"{r['median_seconds']:.1f}"
            note(f"{r['lane']:<10} {r['count']:>5} {_rate(r['recorded_rate']):>8} "
                 f"{_rate(r['used_rate']):>5} {_rate(r['edited_rate']):>6} "
                 f"{_rate(r['discarded_rate']):>9} {med:>8}")
    emit(report=rows, since=a.since)
    return 0
