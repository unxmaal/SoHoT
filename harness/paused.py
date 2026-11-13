"""Paired measurements paused at a time limit: what each needs to resume, and the looks taken at each pause. #813."""
from __future__ import annotations

import json
import time

from harness import run_state

#: The states a paused_runs row can be in. #1730.
PAUSED, STALE, DONE, DEFECT = "paused", "stale", "done", "defect"
STATES = (PAUSED, STALE, DONE, DEFECT)
#: Each legal move of a paused_runs row, (leaves, enters); None is no row yet. Nothing leaves stale, done or defect. #1730.
MOVES = frozenset({(None, PAUSED), (PAUSED, PAUSED), (PAUSED, STALE), (PAUSED, DONE), (PAUSED, DEFECT)})
#: Columns a move may set beside state; `sweeps` is added to, the rest replaced.
_COLS = ("done", "total", "looks", "run_id", "why", "paused_at", "sweeps")

#: What a runs/*-adopt-<lane> directory is to a pairing's pause: these, or the run_state name of one not RESUMABLE. #1730.
EMPTY, RECORDED, OVERRUN, OTHER, ABANDONED = "empty", "recorded", "overrun", "other", "abandoned"
DIR_STATES = (EMPTY, RECORDED, OVERRUN, OTHER, ABANDONED) + tuple(
    s for s in run_state.STATES if s not in run_state.RESUMABLE)


class IllegalMove(RuntimeError):
    """A paused_runs write MOVES does not allow from the row's state, refused before anything is written. #1730."""


def identity(lane: str, inc_spec: str, settings, knobs: dict, split_version: str) -> dict:
    """What must be unchanged for a paused run to resume rather than restart."""
    got = {"lane": (lane or "").strip().lower(), "incumbent": inc_spec, "split_version": split_version,
           "settings": list(settings or ()), "knobs": dict(knobs or {})}
    return json.loads(json.dumps(got, sort_keys=True))   # the shape it is stored in, so equal compares equal


def _here(conn) -> tuple[str, tuple]:
    from harness import machine_scope
    return machine_scope.here(conn, "paused_runs.mine")


def find(conn, lane: str, spec: str) -> dict | None:
    """This machine's live pause of the pairing in this lane, whatever incumbent it ran against."""
    here, args = _here(conn)
    row = conn.execute(f"SELECT * FROM paused_runs WHERE lane = ? AND challenger = ? AND state = ? AND {here} "
                       "ORDER BY id DESC LIMIT 1", ((lane or "").strip().lower(), spec, PAUSED, *args)).fetchone()
    return _row(row) if row else None


def dir_state(conn, out, lane: str, inc_spec: str, spec: str) -> str:
    """The one DIR_STATES name for a paired run directory; only ABANDONED is a resumable pause with no row. #864, #1730."""
    from evals import watch
    from harness import watchdog
    got = watch.read(out)
    if not got or not got[1]:
        return EMPTY
    if conn.execute("SELECT 1 FROM paused_runs WHERE out = ? LIMIT 1", (str(out),)).fetchone():
        return RECORDED
    state = run_state.of(out).name
    if state not in run_state.RESUMABLE:
        return state
    if watchdog.overrun_stopped(conn, out):
        return OVERRUN
    ident = got[0]
    if ident.get("modality") != (lane or "").strip().lower() or list(ident.get("candidates") or ()) != [inc_spec, spec]:
        return OTHER
    return ABANDONED


def abandoned(conn, root, lane: str, inc_spec: str, spec: str) -> dict | None:
    """The newest run directory a stopped paired run left with no pause recorded: its checkpoint is resumable. #864."""
    from pathlib import Path

    from evals import watch
    lane = (lane or "").strip().lower()
    for out in sorted(Path(root).glob(f"*-adopt-{lane}"), reverse=True):
        if dir_state(conn, out, lane, inc_spec, spec) != ABANDONED:
            continue
        ident, rows = watch.read(out)
        return {"id": None, "out": str(out), "plan": None, "looks": [], "checkpoint": ident,
                "done": len(rows), "total": run_state.of(out).progress.get("total") or "?"}
    return None


def waiting(conn) -> list[dict]:
    """This machine's live pauses, oldest first: the next sweep resumes these before starting anything new."""
    here, args = _here(conn)
    return [_row(r) for r in conn.execute(f"SELECT * FROM paused_runs WHERE state = ? AND {here} ORDER BY id",
                                          (PAUSED, *args))]


def _row(r) -> dict:
    got = dict(r)
    for k, empty in (("identity", "{}"), ("plan", "{}"), ("looks", "[]")):
        got[k] = json.loads(got.get(k) or empty)
    return got


def _move(conn, pause_id: int, frm: str, to: str, **cols) -> bool:
    """The one writer of paused_runs.state: refuses a move MOVES does not list, else compare-and-swap on `frm`; False if it lost. #1730."""
    if frm is None or (frm, to) not in MOVES:
        raise IllegalMove(f"pause {pause_id}: no move from {frm} to {to}")
    bad = set(cols) - set(_COLS)
    if bad:
        raise ValueError(f"paused_runs has no movable column {sorted(bad)}")
    sets = "".join(f"{k} = {k} + ?, " if k == "sweeps" else f"{k} = ?, " for k in cols)
    cur = conn.execute(f"UPDATE paused_runs SET {sets}state = ? WHERE id = ? AND state = ?",
                       (*cols.values(), to, pause_id, frm))
    conn.commit()
    return cur.rowcount == 1


def _state(conn, pause_id: int) -> str | None:
    row = conn.execute("SELECT state FROM paused_runs WHERE id = ?", (pause_id,)).fetchone()
    return row[0] if row else None


def save(conn, *, lane: str, inc_spec: str, spec: str, proposal: str, out: str, ident: dict,
         plan: dict, done: int, total: int, looks: list, run_id=None, machine_id=None,
         pause_id: int | None = None, why: str = "", spans: int = 1) -> int:
    """Record or update the pause, adding `spans` sweeps (#1353); IllegalMove for a settled pause or a second live one (#1730)."""
    if pause_id is not None:
        if not _move(conn, pause_id, PAUSED, PAUSED, done=done, total=total, looks=json.dumps(looks),
                     run_id=run_id, sweeps=int(spans), why=why, paused_at=time.time()):
            raise IllegalMove(f"pause {pause_id} is {_state(conn, pause_id) or 'gone'}; a settled pause is never revived")
        return pause_id
    if machine_id is None:
        from harness import memory_store as ms
        machine_id = ms.remember_machine(conn)
    lane = (lane or "").strip().lower()
    cur = conn.execute(
        "INSERT INTO paused_runs (lane, incumbent, challenger, proposal, out, identity, plan, done, total, "
        "sweeps, looks, state, why, run_id, machine_id, paused_at) SELECT ?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,? "
        "WHERE NOT EXISTS (SELECT 1 FROM paused_runs WHERE lane = ? AND challenger = ? AND machine_id = ? "
        "AND state = ?)",
        (lane, inc_spec, spec, proposal, out, json.dumps(ident, sort_keys=True), json.dumps(plan, default=str),
         done, total, json.dumps(looks), PAUSED, why, run_id, machine_id, time.time(),
         lane, spec, machine_id, PAUSED))
    if cur.rowcount != 1:
        conn.rollback()
        raise IllegalMove(f"{lane}: {spec} already has a live pause on machine {machine_id}; resume it, do not add one")
    conn.commit()
    return int(cur.lastrowid)


def settle(conn, pause_id: int, state: str, why: str = "") -> bool:
    """End a live pause as stale, done or defect; False when it was no longer paused (another writer settled it). #1730."""
    if state == PAUSED:
        raise IllegalMove(f"pause {pause_id}: a settle names where the pause ends, not {PAUSED}")
    return _move(conn, pause_id, PAUSED, state, why=why)
