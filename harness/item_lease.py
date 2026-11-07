"""Leases on this machine's resources, one per running item, a queued job or a delegation: taken, beaten, released or lapsed. #1558."""
from __future__ import annotations

import os
import time

#: Seconds a lease lasts past its last beat; a worker gone this long leaves its item to be retaken.
TTL_S = 120.0
#: The resource a delegation leases while it waits for, or is served by, a model on this machine. #1556.
SERVING = "serving"
_LEDGER = "lease-ledger:"


def _machine(conn) -> int | None:
    from harness import memory_store as ms
    return ms.remember_machine(conn)


def _here(conn) -> tuple[str, tuple]:
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    return ("machine_id IS NULL", ()) if mid is None else ("machine_id = ?", (mid,))


def live(conn, resource: str | None = None, now: float | None = None) -> list[dict]:
    """This machine's leases in force at now, oldest first; of one resource if named."""
    now = time.time() if now is None else now
    where, args = _here(conn)
    extra, more = (" AND resource = ?", (resource,)) if resource else ("", ())
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM leases WHERE {where} AND released_at IS NULL AND expires_at > ?{extra} ORDER BY id",
        (*args, now, *more))]


def _capacity(resource: str) -> int | None:
    from harness import resources
    if resource == SERVING:
        return None
    return resources.capacity(resource)


def _version(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else row["value"]


def _bump(conn, key: str, seen: str | None) -> bool:
    """Compare-and-set the ledger's version, so two takers of the last free place cannot both win."""
    if seen is None:
        return conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, '1')", (key,)).rowcount == 1
    return conn.execute("UPDATE meta SET value = ? WHERE key = ? AND value = ?",
                        (str(int(seen) + 1), key, seen)).rowcount == 1


def take(conn, resource: str, item: str, *, job_id=None, pid: int | None = None, priority: int = 0,
         mem_gb: float | None = None, state: str = "", detail: str = "", ttl_s: float = TTL_S,
         now: float | None = None, fits=None) -> dict | None:
    """A lease on `resource` for `item`, or None while the resource is at capacity or `fits(live)` says no."""
    now = time.time() if now is None else now
    mid = _machine(conn)
    conn.commit()
    key = f"{_LEDGER}{mid}"
    for _ in range(8):
        seen = _version(conn, key)
        held = live(conn, now=now)
        cap = _capacity(resource)
        if cap is not None and sum(1 for h in held if h["resource"] == resource) >= cap:
            conn.commit()
            return None
        if fits is not None and not fits(held):
            conn.commit()
            return None
        cur = conn.execute(
            "INSERT INTO leases (machine_id, resource, item, job_id, pid, priority, mem_gb, state, detail, "
            "taken_at, beat_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, resource, item, job_id, os.getpid() if pid is None else int(pid), int(priority), mem_gb, state,
             detail, now, now, now + ttl_s))
        if _bump(conn, key, seen):
            conn.commit()
            return dict(conn.execute("SELECT * FROM leases WHERE id = ?", (cur.lastrowid,)).fetchone())
        conn.rollback()
    return None


def beat(conn, lease_id: int, ttl_s: float = TTL_S, now: float | None = None, **fields) -> bool:
    """Extend a lease ttl_s from now, setting any of state, detail, mem_gb; False once it lapsed or was released."""
    now = time.time() if now is None else now
    sets = "".join(f", {k} = ?" for k in fields)
    got = conn.execute(f"UPDATE leases SET beat_at = ?, expires_at = ?{sets} WHERE id = ? AND released_at IS NULL "
                       "AND expires_at > ?", (now, now + ttl_s, *fields.values(), int(lease_id), now)).rowcount == 1
    conn.commit()
    return got


def release(conn, lease_id: int, now: float | None = None) -> None:
    conn.execute("UPDATE leases SET released_at = ? WHERE id = ? AND released_at IS NULL",
                 (time.time() if now is None else now, int(lease_id)))
    conn.commit()


def of_job(conn, job_id, now: float | None = None) -> dict | None:
    """The lease in force for a queued job, or None."""
    return next((h for h in live(conn, now=now) if h["job_id"] == int(job_id)), None)


def line(h: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    return (f"{h['resource']} leased by {h['item']}{' (' + h['state'] + ')' if h.get('state') else ''} "
            f"for {now - float(h['taken_at']):.0f}s, beat {now - float(h['beat_at']):.0f}s ago")
