"""Download state: the legal moves of downloads.state, each one compare-and-swap on the state it leaves (#1734)."""
from __future__ import annotations

FETCHING, COMPLETE, INCOMPLETE = "fetching", "complete", "incomplete"
#: Complete once, marked for the fetch tier to take again (#799).
STOOD_DOWN = "stood_down"
REMOVED = "removed"
STATES = (FETCHING, COMPLETE, INCOMPLETE, STOOD_DOWN, REMOVED)
#: The state a row "leaves" when it is inserted.
NONE = ""

#: Why a download holds its state: downloads.reason, written with the state by every move.
STARTED = "started"
RECORDED = "recorded"
FINISHED = "finished"
FAILED = "failed"
ABANDONED = "abandoned"
REFETCH = "refetch"
DELETED = "deleted"
HISTORY = "history"
BACKFILL = "backfill"
OFFLINE_GAP = "offline_gap"
REFETCH_CLASS = "refetch_class"
INCOMPLETE_COPY = "incomplete_copy"
NO_SNAPSHOT = "no_snapshot"
#: Reasons that reopen a finished row; a start without one is refused.
REOPEN = frozenset({REFETCH, RECORDED})
STAND_DOWN = frozenset({OFFLINE_GAP, REFETCH_CLASS, INCOMPLETE_COPY, NO_SNAPSHOT})

#: (state it leaves, state it enters) -> the reasons that move may carry. Nothing leaves removed.
MOVES: dict[tuple[str, str], frozenset[str]] = {
    (NONE, FETCHING): frozenset({STARTED}),
    (NONE, REMOVED): frozenset({HISTORY}),
    (FETCHING, FETCHING): frozenset({ABANDONED}),
    (FETCHING, COMPLETE): frozenset({FINISHED}),
    (FETCHING, INCOMPLETE): frozenset({FINISHED, FAILED}),
    (FETCHING, REMOVED): frozenset({DELETED}),
    (COMPLETE, FETCHING): REOPEN,
    (INCOMPLETE, FETCHING): REOPEN,
    (STOOD_DOWN, FETCHING): REOPEN,
    (COMPLETE, STOOD_DOWN): STAND_DOWN,
    (COMPLETE, REMOVED): frozenset({DELETED}),
    (INCOMPLETE, REMOVED): frozenset({DELETED}),
    (STOOD_DOWN, REMOVED): frozenset({DELETED}),
}

#: The columns a move may set beside state, reason and complete.
_COLUMNS = frozenset({"repo", "path", "source", "bytes", "files", "requires", "started_at", "finished_at",
                      "removed_at", "removed_by", "removal_verdict_id"})
#: And the ones only an insert sets.
_BIRTH = _COLUMNS | {"proposal_id", "kind", "file", "origin", "machine_id"}


class IllegalMove(ValueError):
    """A download state write the transition table refuses."""


def refused(frm: str, to: str, reason: str) -> str:
    """Why a download may not move from `frm` to `to` for `reason`, or '' if it may."""
    allowed = MOVES.get((frm, to))
    if allowed is None:
        return f"no download moves from {frm or 'nothing'} to {to}"
    if reason not in allowed:
        return (f"{reason or 'no reason'} does not move a download from {frm or 'nothing'} to {to}; "
                f"it may for {', '.join(sorted(allowed))}")
    return ""


def _check(frm: str, to: str, reason: str, cols: dict, allowed: frozenset) -> None:
    why = refused(frm, to, reason)
    if why:
        raise IllegalMove(why)
    unknown = set(cols) - allowed
    if unknown:
        raise IllegalMove(f"a download move does not set {', '.join(sorted(unknown))}")


def born(conn, to: str, reason: str, **cols) -> int:
    """Insert a download row entering `to`; its id. Does not commit."""
    _check(NONE, to, reason, cols, _BIRTH)
    names = ["state", "reason", "complete", *cols]
    sql = f"INSERT INTO downloads ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
    return conn.execute(sql, (to, reason, 0, *cols.values())).lastrowid


def move(conn, rid, frm: str, to: str, reason: str, **cols) -> bool:
    """Move download rid from `frm` to `to` in one UPDATE guarded by state = frm; True when this writer won. Does not commit."""
    _check(frm, to, reason, cols, _COLUMNS)
    more = "".join(f", {k} = ?" for k in cols)
    sql = f"UPDATE downloads SET state = ?, reason = ?, complete = ?{more} WHERE id = ? AND state = ?"
    args = (to, reason, int(to == COMPLETE), *cols.values(), int(rid), frm)
    return conn.execute(sql, args).rowcount == 1
