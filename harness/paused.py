"""Paired measurements paused at a time limit: what each needs to resume, and the looks taken at each pause. #813."""
from __future__ import annotations

import json
import time


def identity(lane: str, inc_spec: str, settings, knobs: dict, split_version: str) -> dict:
    """What must be unchanged for a paused run to resume rather than restart."""
    got = {"lane": (lane or "").strip().lower(), "incumbent": inc_spec, "split_version": split_version,
           "settings": list(settings or ()), "knobs": dict(knobs or {})}
    return json.loads(json.dumps(got, sort_keys=True))   # the shape it is stored in, so equal compares equal


def find(conn, lane: str, spec: str) -> dict | None:
    """The pairing's live pause in this lane, whatever incumbent it ran against."""
    row = conn.execute("SELECT * FROM paused_runs WHERE lane = ? AND challenger = ? AND state = 'paused' "
                       "ORDER BY id DESC LIMIT 1", ((lane or "").strip().lower(), spec)).fetchone()
    return _row(row) if row else None


def abandoned(conn, root, lane: str, inc_spec: str, spec: str) -> dict | None:
    """The newest run directory a stopped paired run left with no pause recorded: its checkpoint is resumable. #864."""
    from pathlib import Path

    from evals import watch
    from harness import watchdog
    lane = (lane or "").strip().lower()
    known = {r["out"] for r in conn.execute("SELECT out FROM paused_runs")}
    for out in sorted(Path(root).glob(f"*-adopt-{lane}"), reverse=True):
        got = watch.read(out)
        progress = watch.read_progress(out)
        if not got or not got[1] or str(out) in known or progress.get("state") not in ("running", "paused"):
            continue
        if watchdog.overrun_stopped(conn, out):
            continue
        ident = got[0]
        if ident.get("modality") != lane or list(ident.get("candidates") or ()) != [inc_spec, spec]:
            continue
        if _alive(progress.get("pid"), progress.get("pgid")):
            continue
        return {"id": None, "out": str(out), "plan": None, "looks": [], "checkpoint": ident,
                "done": len(got[1]), "total": progress.get("total") or "?"}
    return None


def _alive(pid, pgid) -> bool:
    """Whether the run's process still exists in the group it recorded; a reused pid is in another group."""
    import os
    try:
        pid = int(pid)
        return os.getpgid(pid) == int(pgid if pgid is not None else pid)
    except (TypeError, ValueError, AttributeError, OSError):
        return False


def waiting(conn) -> list[dict]:
    """Every live pause, oldest first: the next sweep resumes these before starting anything new."""
    return [_row(r) for r in conn.execute("SELECT * FROM paused_runs WHERE state = 'paused' ORDER BY id")]


def _row(r) -> dict:
    got = dict(r)
    for k, empty in (("identity", "{}"), ("plan", "{}"), ("looks", "[]")):
        got[k] = json.loads(got.get(k) or empty)
    return got


def save(conn, *, lane: str, inc_spec: str, spec: str, proposal: str, out: str, ident: dict,
         plan: dict, done: int, total: int, looks: list, run_id=None, machine_id=None,
         pause_id: int | None = None, why: str = "", spans: int = 1) -> int:
    """Record or update the pause; a save adds `spans` sweeps, 0 for a later look slice in the same sweep (#1353)."""
    if pause_id is not None:
        conn.execute("UPDATE paused_runs SET done = ?, total = ?, looks = ?, run_id = ?, sweeps = sweeps + ?, "
                     "state = 'paused', why = ?, paused_at = ? WHERE id = ?",
                     (done, total, json.dumps(looks), run_id, int(spans), why, time.time(), pause_id))
        conn.commit()
        return pause_id
    cur = conn.execute(
        "INSERT INTO paused_runs (lane, incumbent, challenger, proposal, out, identity, plan, done, total, "
        "sweeps, looks, state, why, run_id, machine_id, paused_at) VALUES (?,?,?,?,?,?,?,?,?,1,?,'paused',?,?,?,?)",
        ((lane or "").strip().lower(), inc_spec, spec, proposal, out, json.dumps(ident, sort_keys=True),
         json.dumps(plan, default=str), done, total, json.dumps(looks), why, run_id, machine_id, time.time()))
    conn.commit()
    return int(cur.lastrowid)


def settle(conn, pause_id: int, state: str, why: str = "") -> None:
    conn.execute("UPDATE paused_runs SET state = ?, why = ? WHERE id = ?", (state, why, pause_id))
    conn.commit()
