"""Eric's machine-wide day clearance: jobs may run all day until that day's watchdog day end. #1112."""
from __future__ import annotations

import time
from datetime import datetime


def day_end(now: float) -> float:
    """The watchdog's day end (watchdog_day_end_hour) on now's calendar day."""
    from harness import watchdog
    return datetime.fromtimestamp(now).replace(hour=watchdog.DAY_END_HOUR, minute=0, second=0,
                                               microsecond=0).timestamp()


def _here(conn) -> tuple[str, tuple]:
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    return ("machine_id IS NULL", ()) if mid is None else ("machine_id = ?", (mid,))


def active(conn, now: float | None = None) -> dict | None:
    """This machine's clearance in force at now, the latest if several; None when there is none."""
    now = time.time() if now is None else now
    where, args = _here(conn)
    r = conn.execute(f"SELECT * FROM day_clearances WHERE {where} AND revoked_at IS NULL AND cleared_at <= ? "
                     "AND until > ? ORDER BY id DESC LIMIT 1", (*args, now, now)).fetchone()
    return dict(r) if r else None


def clear(conn, said: str, now: float | None = None) -> dict:
    """Record a clearance until today's day end; refused without who and why, or once the day is over."""
    from harness import memory_store as ms
    said = (said or "").strip()
    if not said:
        raise ValueError('a day clearance names who gave it and why: soh day clear "eric: the #1110 baseline"')
    now = time.time() if now is None else now
    until = day_end(now)
    if until <= now:
        raise ValueError(f"the day hours ended at {time.strftime('%H:%M', time.localtime(until))}; nothing is "
                         "held back at night, and a clearance never carries over to tomorrow")
    cur = conn.execute("INSERT INTO day_clearances (machine_id, cleared_at, said, until) VALUES (?,?,?,?)",
                       (ms.remember_machine(conn), now, said, until))
    conn.commit()
    return dict(conn.execute("SELECT * FROM day_clearances WHERE id = ?", (cur.lastrowid,)).fetchone())


def revoke(conn, now: float | None = None) -> dict | None:
    """End every clearance of this machine in force now; the latest of them, or None when none was."""
    now = time.time() if now is None else now
    got = active(conn, now)
    if got is None:
        return None
    where, args = _here(conn)
    conn.execute(f"UPDATE day_clearances SET revoked_at = ? WHERE {where} AND revoked_at IS NULL AND until > ?",
                 (now, *args, now))
    conn.commit()
    return {**got, "revoked_at": now}


def since(conn, start: float, now: float) -> list[dict]:
    """This machine's clearances in force at any point in [start, now], oldest first."""
    where, args = _here(conn)
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM day_clearances WHERE {where} AND cleared_at <= ? AND COALESCE(revoked_at, until) >= ? "
        "ORDER BY id", (*args, now, start))]


def hm(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


def line(c: dict, now: float | None = None) -> str:
    """One line on a clearance: who and why, and until when."""
    now = time.time() if now is None else now
    if c.get("revoked_at") is not None:
        state = f"revoked at {hm(c['revoked_at'])}"
    elif c["until"] <= now:
        state = f"expired at {hm(c['until'])}"
    else:
        state = f"until {hm(c['until'])}"
    return f"day clearance from {hm(c['cleared_at'])} {state}: {c['said']}"
