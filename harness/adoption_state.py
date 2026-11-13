"""What a lane serves on a machine: adoptions are named moves on one chain per lane, one CAS writer, one resolver (#1735)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

from harness import store

#: The moves an adoptions row records: a model starts serving, or the serving one is withdrawn.
ADOPT, WITHDRAW = "adopt", "withdraw"
KINDS = (ADOPT, WITHDRAW)

#: What a lane is on a machine.
ADOPTED = "adopted"
WITHDRAWN = "withdrawn"
CONFIGURED = "configured"
NONE = "none"
STATES = (ADOPTED, WITHDRAWN, CONFIGURED, NONE)

#: (state the lane leaves on the writer's machine, move) -> the state it enters. Only a served adoption is withdrawn.
MOVES: dict[tuple[str, str], str] = {
    (NONE, ADOPT): ADOPTED,
    (CONFIGURED, ADOPT): ADOPTED,
    (WITHDRAWN, ADOPT): ADOPTED,
    (ADOPTED, ADOPT): ADOPTED,
    (ADOPTED, WITHDRAW): WITHDRAWN,
}

#: The machine argument meaning this machine (adopt.HERE); None is no machine, as in adopt.current.
HERE = object()

_SAYS = {CONFIGURED: "configured default, never adopted here", NONE: "no adoption and no configured default"}


class IllegalMove(ValueError):
    """An adoption move MOVES does not allow from the lane's state on the writer's machine."""


class Lost(RuntimeError):
    """Another writer moved the lane after this one read its head; nothing was written."""


@dataclass(frozen=True)
class Served:
    """One lane on one machine: its state, what serves, the row that put it there, a newer by-hand row refused by fit."""
    lane: str
    state: str
    spec: str
    row: dict | None = None
    refused: dict | None = None

    @property
    def candidate_id(self) -> int | None:
        return self.row["candidate_id"] if self.state == ADOPTED else None

    def says(self) -> str:
        if self.state == ADOPTED:
            out = f"adopted {self.spec} (adoption {self.row['id']}, {self.row['how']})"
        elif self.state == WITHDRAWN:
            out = (f"configured default {self.spec or '(none)'}; adoption of {self.row['spec']} withdrawn "
                   f"(adoption {self.row['id']}): {self.row.get('why') or 'no reason given'}")
        else:
            out = f"{_SAYS[self.state]}{': ' + self.spec if self.spec else ''}"
        if self.refused:
            out += f"; newer by-hand {self.refused['spec']} refused here: {self.refused['why']}"
        return out


def _rows(conn, lane: str | None) -> list[dict]:
    where, args = (" WHERE a.lane = ?", (lane,)) if lane else ("", ())
    return [dict(r) for r in conn.execute(
        "SELECT a.*, c.spec, i.spec AS incumbent FROM adoptions a JOIN candidates c ON c.id = a.candidate_id "
        f"LEFT JOIN candidates i ON i.id = a.incumbent_id{where} ORDER BY a.id", args).fetchall()]


def chains(conn, lane: str | None = None) -> dict[str, list[dict]]:
    """lane -> its adoptions oldest first, each the row after the one it leaves; a row off the chain is not in it."""
    by: dict[str, list[dict]] = {}
    for r in _rows(conn, lane):
        by.setdefault(r["lane"], []).append(r)
    out = {}
    for name, rows in by.items():
        after = {r["leaves"]: r for r in rows}
        got, at = [], 0
        while at in after and len(got) < len(rows):
            got.append(after[at])
            at = after[at]["id"]
        out[name] = got
    return out


def off_chain(conn) -> list[dict]:
    """Adoption rows no chain reaches (a deleted predecessor or a hand-written row)."""
    on = {r["id"] for rows in chains(conn).values() for r in rows}
    return [r for r in _rows(conn, None) if r["id"] not in on]


def _ids(conn, machine) -> tuple:
    from harness import adopt
    return adopt._ids(conn, adopt.HERE if machine is HERE else machine)


def _applies(row: dict, ids: tuple) -> bool:
    from harness import machine_scope
    return bool(row["all_machines"]) or machine_scope.holds("adoptions.served", row["machine_id"], ids)


def _resolve(conn, lane: str, rows: list[dict], ids: tuple, default: str) -> Served:
    from harness import adopt
    refused = None
    for r in reversed(rows):
        if not _applies(r, ids):
            continue
        if r["move"] == WITHDRAW:
            return Served(lane, WITHDRAWN, default, r, refused)
        if adopt.is_reference(r["spec"]):
            continue
        if r["how"] == adopt.BY_HAND:
            ok, why = adopt.fit(conn, r["candidate_id"], ids[0] if ids else None)
            if not ok:
                refused = refused or {**r, "why": why}
                continue
        return Served(lane, ADOPTED, r["spec"], r, refused)
    return Served(lane, CONFIGURED if default else NONE, default, None, refused)


def table(conn, machine=HERE, typed=None, lane: str | None = None) -> dict[str, Served]:
    """lane -> Served on a machine (an id, ids, HERE or adopt.HERE), for every lane typed or an adoption names."""
    if typed is None:
        from harness import winners
        typed = winners.typed()
    ids = _ids(conn, machine)
    got = chains(conn, lane)
    names = {lane} if lane else set(typed) | set(got)
    return {n: _resolve(conn, n, got.get(n, []), ids, typed.get(n, "")) for n in sorted(names)}


def serving(conn, lane: str, machine=HERE, typed=None) -> Served:
    """What serves one lane on a machine, and which named state says so."""
    key = lane.strip().lower()
    return table(conn, machine, typed, key)[key]


def history(conn, machine=None, lane: str | None = None, since: float | None = None,
            verdict_id: int | None = None) -> list[dict]:
    """Every adoption move oldest first, with spec and incumbent; `machine` keeps those that apply there."""
    rows = [r for rows in chains(conn, lane).values() for r in rows]
    if machine is not None:
        ids = _ids(conn, machine)
        rows = [r for r in rows if _applies(r, ids)]
    if since is not None:
        rows = [r for r in rows if r["adopted_at"] >= since]
    if verdict_id is not None:
        rows = [r for r in rows if r["verdict_id"] == verdict_id]
    return sorted(rows, key=lambda r: (r["adopted_at"], r["id"]))


def move(conn, lane: str, kind: str, candidate_id: int, *, how: str, machine_id, why: str = "",
         all_machines: bool = False, head: int | None = None, verdict_id: int | None = None,
         run_id: int | None = None, incumbent_id: int | None = None, votes=None, agreement=None,
         forced: bool = False, cost: dict | None = None) -> int:
    """The one writer of adoptions: one row leaving the lane's head (`head`, read now when None); Lost when another won.

    Commits. A verdict already adopted returns its row unchanged.
    """
    lane = lane.strip().lower()
    if kind not in KINDS:
        raise IllegalMove(f"no adoption move named {kind!r}; moves are {', '.join(KINDS)}")
    if verdict_id is not None:
        got = conn.execute("SELECT id FROM adoptions WHERE verdict_id = ?", (verdict_id,)).fetchone()
        if got:
            return got["id"]
    rows = chains(conn, lane).get(lane, [])
    now = rows[-1]["id"] if rows else 0
    if head is not None and head != now:
        raise Lost(f"{lane}: adoption {now} moved the lane after this writer read adoption {head}")
    here = _resolve(conn, lane, rows, () if machine_id is None else (machine_id,), "")
    enters = MOVES.get((here.state, kind))
    if enters is None:
        raise IllegalMove(f"{lane} is {here.state} on machine {machine_id}; {kind} does not move it")
    from harness import adopt
    spec = conn.execute("SELECT spec FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
    if kind == ADOPT and spec and adopt.is_reference(spec["spec"]):
        raise IllegalMove(f"{spec['spec']} is a reference model; never a lane default (#374)")
    if kind == WITHDRAW and here.candidate_id != candidate_id:
        raise IllegalMove(f"{lane} serves {here.spec} on machine {machine_id}, not candidate {candidate_id}")
    try:
        cur = conn.execute(
            "INSERT INTO adoptions (lane, candidate_id, incumbent_id, run_id, verdict_id, machine_id, how, adopted_at, "
            "all_machines, votes, agreement, forced, cost, move, why, leaves) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lane, candidate_id, incumbent_id, run_id, verdict_id, machine_id, how, time.time(), int(all_machines),
             votes, agreement, int(forced), json.dumps(cost or {}, sort_keys=True), kind, why, now))
    except store.IntegrityError as exc:
        conn.rollback()
        raise Lost(f"{lane}: another writer left adoption {now} first ({exc})") from exc
    conn.commit()
    return int(cur.lastrowid)


def withdraw(conn, lane: str, why: str, machine=HERE, all_machines: bool = False) -> int:
    """Withdraw what a lane serves by adoption on a machine; its configured default serves there."""
    from harness import adopt
    from harness import memory_store as ms
    if not why.strip():
        raise IllegalMove("a withdrawal says why")
    ids = _ids(conn, machine)
    mid = ids[0] if ids else ms.remember_machine(conn)
    lane = lane.strip().lower()
    rows = chains(conn, lane).get(lane, [])
    here = _resolve(conn, lane, rows, (mid,), "")
    if here.state != ADOPTED:
        raise IllegalMove(f"{lane} has no adoption serving on machine {mid} to withdraw ({here.state})")
    return move(conn, lane, WITHDRAW, here.candidate_id, how=adopt.BY_HAND, machine_id=mid, why=why.strip(),
                all_machines=all_machines, head=rows[-1]["id"], incumbent_id=here.candidate_id)
