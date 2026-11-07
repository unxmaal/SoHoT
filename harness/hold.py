"""The owner's benchmark hold: no discovery sweep, reverify, knob sweep or measurement job starts while it is in force. #1564."""
from __future__ import annotations

import time

BENCHMARKS = "benchmarks"
#: soh verbs that measure or sweep; a job running one waits out a hold.
VERBS = ("adopt", "reverify", "discover")
#: Planners whose queued jobs are measurement whatever their command.
PLANNERS = ("sweep", "reverify", "adopt")
RELEASE = "soh hold release"


def _here(conn) -> tuple[str, tuple]:
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    return ("machine_id IS NULL", ()) if mid is None else ("machine_id = ?", (mid,))


def _has(conn) -> bool:
    try:
        conn.execute("SELECT 1 FROM holds LIMIT 1").fetchall()
    except Exception:  # noqa: BLE001 - a store from before schema 90 has no holds
        return False
    return True


def active(conn, now: float | None = None) -> dict | None:
    """This machine's benchmark hold in force at now, the latest if several; None when there is none."""
    if not _has(conn):
        return None
    now = time.time() if now is None else now
    where, args = _here(conn)
    r = conn.execute(f"SELECT * FROM holds WHERE {where} AND kind = ? AND released_at IS NULL AND held_at <= ? "
                     "AND (until IS NULL OR until > ?) ORDER BY id DESC LIMIT 1",
                     (*args, BENCHMARKS, now, now)).fetchone()
    return dict(r) if r else None


def hold(conn, said: str, until: float | None = None, now: float | None = None) -> dict:
    """Hold benchmarking until released, or until `until`; refused without who and why."""
    from harness import memory_store as ms
    said = (said or "").strip()
    if not said:
        raise ValueError('a hold names who placed it and why: soh hold benchmarks "owner: the #1558 rebuild"')
    now = time.time() if now is None else now
    if until is not None and until <= now:
        raise ValueError(f"the hold would end at {_at(until)}, which has passed")
    cur = conn.execute("INSERT INTO holds (machine_id, kind, held_at, said, until) VALUES (?,?,?,?,?)",
                       (ms.remember_machine(conn), BENCHMARKS, now, said, until))
    conn.commit()
    return dict(conn.execute("SELECT * FROM holds WHERE id = ?", (cur.lastrowid,)).fetchone())


def release(conn, now: float | None = None) -> dict | None:
    """End every benchmark hold of this machine in force now; the latest of them, or None when none was."""
    now = time.time() if now is None else now
    got = active(conn, now)
    if got is None:
        return None
    where, args = _here(conn)
    conn.execute(f"UPDATE holds SET released_at = ? WHERE {where} AND kind = ? AND released_at IS NULL "
                 "AND (until IS NULL OR until > ?)", (now, *args, BENCHMARKS, now))
    conn.commit()
    return {**got, "released_at": now}


def _at(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def line(h: dict, now: float | None = None) -> str:
    """One line on a hold: since when, who and why, and until when."""
    now = time.time() if now is None else now
    if h.get("released_at") is not None:
        state = f", released {_at(h['released_at'])}"
    elif h.get("until") is not None:
        state = f", {'ended' if h['until'] <= now else 'until'} {_at(h['until'])}"
    else:
        state = f", until {RELEASE}"
    return f"benchmarks held since {_at(h['held_at'])}{state}: {h['said']}"


def held(conn=None, now: float | None = None) -> str:
    """The line of the hold in force, '' when none is."""
    from harness import workqueue as wq
    with wq._store(conn) as c:
        h = active(c, now)
        return line(h, now) if h else ""


def measurement(job: dict) -> bool:
    """Whether a queued job measures or sweeps: evals.run, soh adopt/reverify/discover, or a sweep or reverify planner's."""
    if job.get("requested_by") in PLANNERS:
        return True
    words = [w for a in job.get("argv") or [] for w in str(a).split()]
    if "evals.run" in words:
        return True
    for i, w in enumerate(words):
        if w.rsplit("/", 1)[-1] in ("soh", "lh") or w == "harness.cli":
            return next((x for x in words[i + 1:] if not x.startswith("-")), "") in VERBS
    return False


def _key(job) -> int | None:
    from harness import workqueue as wq
    return wq._key(job["id"] if isinstance(job, dict) else job)


def passed(conn, job) -> bool:
    """Whether the owner let this job start through a hold."""
    r = conn.execute("SELECT despite_hold FROM jobs WHERE id = ?", (_key(job),)).fetchone()
    return bool(r and r["despite_hold"])


def let(conn, job_id) -> None:
    """Let one pending job start through a hold."""
    from harness import workqueue as wq
    cur = conn.execute("UPDATE jobs SET despite_hold = 1 WHERE id = ? AND state = ?", (_key(job_id), wq.PENDING))
    conn.commit()
    if not cur.rowcount:
        raise ValueError(f"no pending job {job_id}")


def held_back(conn, job: dict, h: dict | None) -> bool:
    return h is not None and measurement(job) and not passed(conn, job)


def startable(jobs: list[dict], conn=None, now: float | None = None) -> list[dict]:
    """The jobs a benchmark hold lets start: all but measurement jobs the owner did not let through."""
    from harness import workqueue as wq
    if not jobs:
        return jobs
    with wq._store(conn) as c:
        h = active(c, now)
        return [j for j in jobs if not held_back(c, j, h)]
