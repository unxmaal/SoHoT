"""A gateway alias switch's one declared state, moved only by compare-and-swap on the state it leaves (#1736)."""
from __future__ import annotations

import os
import re
import subprocess
import time

from harness import proc_identity, store

PS_TIMEOUT_S = 5.0
#: A start time as proc_identity keeps it; any other gateway_switch_runs.started is a ps lstart written before #1820.
_PROC_STARTED = re.compile(r"\d+(\.\d+)?")

NONE = ""
REQUESTED, WRITING, RESTARTING, SERVING, FAILED = "requested", "writing", "restarting", "serving", "failed"
STATES = (REQUESTED, WRITING, RESTARTING, SERVING, FAILED)
#: A switch in these states holds the one in-flight slot (gateway_switch_runs.live = 1).
LIVE = (REQUESTED, WRITING, RESTARTING)

#: Why a switch holds its state: gateway_switch_runs.reason, written with the state by every move.
CLAIMED = "claimed"
QUIET = "quiet"
RETRY = "retry"
WRITTEN = "written"
SERVED = "served"
UNCHANGED = "unchanged"
FINISHED = "finished"
NO_RESTART = "no_restart"
GAVE_UP = "gave_up"
RAISED = "raised"
DIED = "died"
SUPERSEDED = "superseded"
#: A switch the worker started again whose process never claimed its row in time; a death for the respawn bound. #1904.
UNCLAIMED = "unclaimed"
#: A respawn's own claim made after it was settled unclaimed: refused before it switches, and no death. #1940.
LATE = "late"

#: (state it leaves, state it enters) -> the reasons that move may carry. Nothing leaves serving or failed.
MOVES: dict[tuple[str, str], frozenset[str]] = {
    (NONE, REQUESTED): frozenset({CLAIMED}),
    (REQUESTED, WRITING): frozenset({QUIET}),
    (RESTARTING, WRITING): frozenset({RETRY}),
    (WRITING, RESTARTING): frozenset({WRITTEN}),
    (RESTARTING, SERVING): frozenset({SERVED, FINISHED}),
    (REQUESTED, SERVING): frozenset({UNCHANGED}),
    (REQUESTED, FAILED): frozenset({NO_RESTART, RAISED, DIED, UNCLAIMED, LATE}),
    (WRITING, FAILED): frozenset({RAISED, DIED, SUPERSEDED}),
    (RESTARTING, FAILED): frozenset({GAVE_UP, RAISED, DIED, SUPERSEDED}),
}

#: The columns a move may set beside state, reason, live and updated_at; and the ones only a claim sets.
_COLUMNS = frozenset({"before", "target", "moved", "detail"})
_BIRTH = _COLUMNS | {"pid", "pgid", "started", "requested_at", "config"}

#: What a switch is, as `soh report` shows it: its live state, or how the served config stands with none in flight.
ORPHANED = "orphaned"
STALE = "stale"
UNWRITTEN = "unwritten"


class IllegalMove(ValueError):
    """A switch state write the transition table refuses."""


class Lost(RuntimeError):
    """Another switch holds the in-flight slot; nothing was written."""


def refused(frm: str, to: str, reason: str) -> str:
    """Why a switch may not move from `frm` to `to` for `reason`, or '' if it may."""
    allowed = MOVES.get((frm, to))
    if allowed is None:
        return f"no gateway switch moves from {frm or 'nothing'} to {to}"
    if reason not in allowed:
        return (f"{reason or 'no reason'} does not move a gateway switch from {frm or 'nothing'} to {to}; "
                f"it may for {', '.join(sorted(allowed))}")
    return ""


def _check(frm: str, to: str, reason: str, cols: dict, allowed: frozenset) -> None:
    why = refused(frm, to, reason)
    if why:
        raise IllegalMove(why)
    unknown = set(cols) - allowed
    if unknown:
        raise IllegalMove(f"a gateway switch move does not set {', '.join(sorted(unknown))}")


def claim(conn, now: float | None = None, **cols) -> int:
    """Insert a requested switch holding the one in-flight slot; its id. Raises Lost when another holds it. Commits."""
    _check(NONE, REQUESTED, CLAIMED, cols, _BIRTH)
    names = ["state", "reason", "live", "updated_at", *cols]
    sql = (f"INSERT INTO gateway_switch_runs ({', '.join(names)}) "
           f"VALUES ({', '.join('?' * len(names))})")
    try:
        rid = conn.execute(sql, (REQUESTED, CLAIMED, 1, time.time() if now is None else now,
                                 *cols.values())).lastrowid
        conn.commit()
    except store.IntegrityError as exc:
        conn.rollback()
        raise Lost(f"another gateway switch is in flight: {exc}") from exc
    return rid


def move(conn, rid, frm: str, to: str, reason: str, now: float | None = None, **cols) -> bool:
    """Move switch rid from `frm` to `to` in one UPDATE guarded by state = frm; True when this writer won. Commits."""
    _check(frm, to, reason, cols, _COLUMNS)
    more = "".join(f", {k} = ?" for k in cols)
    sql = (f"UPDATE gateway_switch_runs SET state = ?, reason = ?, live = ?, updated_at = ?{more} "
           f"WHERE id = ? AND state = ?")
    args = (to, reason, 1 if to in LIVE else None, time.time() if now is None else now,
            *cols.values(), int(rid), frm)
    won = conn.execute(sql, args).rowcount == 1
    conn.commit()
    return won


def live(conn) -> dict | None:
    """The switch holding the in-flight slot, or None."""
    row = conn.execute("SELECT * FROM gateway_switch_runs WHERE live = 1").fetchone()
    return dict(row) if row else None


def deaths(conn, requested_at) -> int:
    """How many switches for the adoption requested at `requested_at` died or never claimed their row. #1899, #1904."""
    return int(conn.execute("SELECT COUNT(*) FROM gateway_switch_runs WHERE requested_at = ? AND state = ? "
                            "AND reason IN (?, ?)", (requested_at, FAILED, DIED, UNCLAIMED)).fetchone()[0])


def get(conn, rid) -> dict | None:
    row = conn.execute("SELECT * FROM gateway_switch_runs WHERE id = ?", (int(rid),)).fetchone()
    return dict(row) if row else None


def started(pid: int) -> str:
    """The process's start time as proc_identity reads it, '' when it cannot say. #1820."""
    return proc_identity.started(pid)


def me() -> dict:
    """This process's identity, for claim(): pid, process group and start time."""
    return proc_identity.identity(os.getpid())


def _lstart(pid: int) -> str:
    """The start time as `ps -o lstart` prints it, how rows claimed before #1820 recorded it; '' when it cannot say."""
    try:
        out = subprocess.run(["ps", "-o", "lstart=", "-p", str(int(pid))], capture_output=True,
                             text=True, timeout=PS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return ""
    return " ".join(out.stdout.split()) if out.returncode == 0 else ""


def alive(row: dict) -> bool | None:
    """Whether the process a switch row names still runs: same pid, same group and same start time; None when it cannot say."""
    recorded = str(row.get("started") or "")
    if not recorded or not row.get("pid") or _PROC_STARTED.fullmatch(recorded):
        return proc_identity.same(row)
    if proc_identity.same({**row, "started": ""}) is False:
        return False
    now = _lstart(int(row["pid"]))
    return (now == recorded) if now else None
