"""A named lease in the store's meta table, so one machine of several sharing a store does a job. #703."""
from __future__ import annotations

import json
import os
import time

PREFIX = "lease:"


def _key(name: str) -> str:
    return PREFIX + name


def _encode(owner: dict, now: float, ttl_s: float) -> str:
    return json.dumps({**owner, "since": now, "expires": now + ttl_s}, sort_keys=True)


def _decode(raw) -> dict:
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _raw(conn, name: str):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_key(name),)).fetchone()
    return None if row is None else row["value"]


def holder(conn, name: str) -> dict:
    """Who holds the lease, or {}."""
    raw = _raw(conn, name)
    return {} if raw is None else _decode(raw)


def owner(conn) -> dict:
    """This process on this machine, as a lease names its holder."""
    from harness import memory_store as ms
    return {"machine_id": ms.remember_machine(conn), "pid": os.getpid()}


def take(conn, name: str, who: dict, ttl_s: float, now: float | None = None,
         alive=None) -> dict:
    """{} once `who` holds the lease for ttl_s, else the holder that kept it."""
    now = time.time() if now is None else now
    alive = alive or (lambda pid: True)
    mine = _encode(who, now, ttl_s)
    for _ in range(3):
        if conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                        (_key(name), mine)).rowcount == 1:
            conn.commit()
            return {}
        raw = _raw(conn, name)
        if raw is None:
            continue
        current = _decode(raw)
        expired = float(current.get("expires") or 0) <= now
        orphaned = (current.get("machine_id") == who.get("machine_id")
                    and current.get("pid") is not None and not alive(current["pid"]))
        if not (expired or orphaned):
            conn.commit()
            return current
        # Compare-and-set on the value read, so two takers of a stale lease cannot both win.
        if conn.execute("UPDATE meta SET value = ? WHERE key = ? AND value = ?",
                        (mine, _key(name), raw)).rowcount == 1:
            conn.commit()
            return {}
        conn.rollback()
    return holder(conn, name)


def _same(current: dict, who: dict) -> bool:
    return bool(current) and (current.get("machine_id"), current.get("pid")) == (
        who.get("machine_id"), who.get("pid"))


def renew(conn, name: str, who: dict, ttl_s: float, now: float | None = None) -> bool:
    """Extend the lease `who` still holds by ttl_s from now; False once someone else holds it."""
    now = time.time() if now is None else now
    raw = _raw(conn, name)
    current = {} if raw is None else _decode(raw)
    if not _same(current, who):
        conn.commit()
        return False
    kept = conn.execute("UPDATE meta SET value = ? WHERE key = ? AND value = ?",
                        (_encode(who, now, ttl_s), _key(name), raw)).rowcount == 1
    conn.commit()
    return kept


def release(conn, name: str, who: dict) -> bool:
    """Drop the lease if `who` holds it; whether it did."""
    raw = _raw(conn, name)
    current = {} if raw is None else _decode(raw)
    if not _same(current, who):
        conn.commit()
        return False
    gone = conn.execute("DELETE FROM meta WHERE key = ? AND value = ?",
                        (_key(name), raw)).rowcount == 1
    conn.commit()
    return gone
