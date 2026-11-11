"""Queue job state: the legal moves of jobs.state, each one compare-and-swap on the state it leaves (#1728)."""
from __future__ import annotations

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
CANCELLED = "cancelled"
#: A job whose command paused on request with its work checkpointed (evals.watch.PAUSED). #1357.
PAUSED = "paused"

#: Why a job holds its state: jobs.reason, written with the state by every move.
ADDED = "added"
CLAIMED = "claimed"
UNCLAIMED = "unclaimed"
NEXT_ITEM = "next_item"
DEPLOY_PAUSE = "deploy_pause"
CONTENTION_PAUSE = "contention_pause"
DEPLOY_STOP = "deploy_stop"
WORKER_GONE = "worker_gone"
EXITED = "exited"
NOT_STARTED = "not_started"
INTERRUPTED = "interrupted"
CHECKPOINTED = "checkpointed"
CONTINUED = "continued"
CANCEL = "cancel"
SUPERSEDED = "superseded"
DEPLOYED = "deployed"
DEPLOY_FAILED = "deploy_failed"
HANDED_OFF = "handed_off"

#: (state it leaves, state it enters) -> the reasons that move may carry. Nothing leaves done, failed, cancelled or paused.
MOVES: dict[tuple[str, str], frozenset[str]] = {
    (PENDING, RUNNING): frozenset({CLAIMED}),
    (PENDING, CANCELLED): frozenset({CANCEL, SUPERSEDED}),
    (RUNNING, PENDING): frozenset({UNCLAIMED, NEXT_ITEM, DEPLOY_PAUSE, CONTENTION_PAUSE, DEPLOY_STOP, WORKER_GONE}),
    (RUNNING, DONE): frozenset({EXITED, DEPLOYED}),
    (RUNNING, FAILED): frozenset({EXITED, NOT_STARTED, INTERRUPTED, DEPLOY_FAILED}),
    (RUNNING, PAUSED): frozenset({CHECKPOINTED, CONTINUED}),
    (RUNNING, CANCELLED): frozenset({CANCEL}),
}

#: The flag files beside a running job's pid file (workqueue._pids), read only to choose its exit move.
CANCEL_FLAG, STOP_FLAG, ITEM_FLAG, DEPLOY_FLAG = "cancel", "stopped", "item", "deploy"
FLAGS = (CANCEL_FLAG, STOP_FLAG, ITEM_FLAG, DEPLOY_FLAG)

#: The columns a move may set beside state, reason and note.
_COLUMNS = frozenset({"started_at", "finished_at", "rc", "log", "argv", "machine_id"})


class IllegalMove(ValueError):
    """A job state write the transition table refuses."""


def refused(frm: str, to: str, reason: str) -> str:
    """Why a job may not move from `frm` to `to` for `reason`, or '' if it may."""
    allowed = MOVES.get((frm, to))
    if allowed is None:
        return f"no job moves from {frm or 'nothing'} to {to}"
    if reason not in allowed:
        return f"{reason or 'no reason'} does not move a job from {frm} to {to}; it may for {', '.join(sorted(allowed))}"
    return ""


def move(conn, job_id, frm: str, to: str, reason: str, note: str | None = None,
         where: str = "", args: tuple = (), **cols) -> bool:
    """Move job_id from `frm` to `to` in one UPDATE guarded by state = frm; True when this writer won. Does not commit."""
    why = refused(frm, to, reason)
    if why:
        raise IllegalMove(why)
    unknown = set(cols) - _COLUMNS
    if unknown:
        raise IllegalMove(f"a move does not set {', '.join(sorted(unknown))}")
    sets, vals = [], []
    if note is not None:
        sets.append("note = ?")
        vals.append(note)
    for k, v in cols.items():
        sets.append(f"{k} = ?")
        vals.append(v)
    more, tail = "".join(f", {s}" for s in sets), f" AND {where}" if where else ""
    sql = f"UPDATE jobs SET state = ?, reason = ?{more} WHERE id = ? AND state = ?{tail}"
    return conn.execute(sql, (to, reason, *vals, int(job_id), frm, *args)).rowcount == 1


def exit_move(rc, flags, handed_off: bool = False, contended: bool = False) -> tuple[str, str]:
    """(state, reason) a running job's exit moves it to: cancel > deploy stop > deploy hand-off > rc, then item > deploy pause > contention."""
    from evals import watch
    if CANCEL_FLAG in flags:
        return CANCELLED, CANCEL
    if STOP_FLAG in flags:
        return PENDING, DEPLOY_STOP
    if handed_off:
        return RUNNING, HANDED_OFF
    if rc == 0:
        return DONE, EXITED
    if rc != watch.PAUSED:
        return FAILED, EXITED
    if ITEM_FLAG in flags:
        return PENDING, NEXT_ITEM
    if DEPLOY_FLAG in flags:
        return PENDING, DEPLOY_PAUSE
    if contended:
        return PENDING, CONTENTION_PAUSE
    return PAUSED, CHECKPOINTED


def gone_move(flags, resumable: bool) -> tuple[str, str]:
    """(state, reason) for a running job whose worker and process are gone: cancel > deploy stop > resume > interrupted."""
    if CANCEL_FLAG in flags:
        return CANCELLED, CANCEL
    if STOP_FLAG in flags:
        return PENDING, DEPLOY_STOP
    if resumable:
        return PENDING, WORKER_GONE
    return FAILED, INTERRUPTED
