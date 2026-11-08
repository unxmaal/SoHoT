"""The owner's hold, one per scope: benchmarks (sweeps, reverifies, measurement jobs) or gpu (every batch GPU job and deploy). #1564, #1509, #1508."""
from __future__ import annotations

import json
import time

BENCHMARKS = "benchmarks"
GPU = "gpu"
#: What each scope stops, said wherever a hold is shown.
SCOPES = {
    BENCHMARKS: "the discover loop starts no sweep, reverify and knob sweeps queue nothing, and the queue starts no "
                "evals.run, adopt, reverify or discover job; deploys, serving and other jobs still run. "
                "soh hold let JOB (or soh jobs add --despite-hold) lets one measurement job through",
    GPU: "no batch GPU job or deploy starts, and the watchdog pauses a running one at its next case; "
         "cloud evals and what an MCP client waits on still run",
}
#: soh verbs that measure or sweep; a job running one waits out a benchmark hold.
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


def _scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"a hold's scope is one of {', '.join(SCOPES)}, not {scope!r}")
    return scope


def _legacy_path():
    from harness import paths
    return paths.home() / "queue" / "hold"


def _legacy(now: float) -> dict | None:
    """A gpu hold `soh gate hold` left as a file before the scopes; an unreadable one still holds. #1509."""
    path = _legacy_path()
    if not path.exists():
        return None
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        got = {"said": f"unreadable hold file {path}: {exc}"}
    until = got.get("until")
    if until is not None and float(until) <= now:
        return None
    return {"id": None, "kind": GPU, "held_at": float(got.get("at") or now), "said": str(got.get("said") or ""),
            "until": until, "released_at": None, "file": str(path)}


def active(conn, now: float | None = None, scope: str = BENCHMARKS) -> dict | None:
    """This machine's hold of `scope` in force at now, the latest if several; None when there is none."""
    now = time.time() if now is None else now
    if _has(conn):
        where, args = _here(conn)
        r = conn.execute(f"SELECT * FROM holds WHERE {where} AND kind = ? AND released_at IS NULL AND held_at <= ? "
                         "AND (until IS NULL OR until > ?) ORDER BY id DESC LIMIT 1",
                         (*args, _scope(scope), now, now)).fetchone()
        if r:
            return dict(r)
    return _legacy(now) if scope == GPU else None


def actives(conn, now: float | None = None) -> list[dict]:
    """Every scope's hold in force at now, in SCOPES order."""
    return [h for h in (active(conn, now, s) for s in SCOPES) if h]


def hold(conn, said: str, until: float | None = None, now: float | None = None, scope: str = BENCHMARKS) -> dict:
    """Hold `scope` until released, or until `until`; refused without who and why."""
    from harness import memory_store as ms
    said = " ".join((said or "").split())
    if not said:
        raise ValueError(f'a hold names who placed it and why: soh hold {scope} "owner: the #1558 rebuild"')
    now = time.time() if now is None else now
    if until is not None and until <= now:
        raise ValueError(f"the hold would end at {_at(until)}, which has passed")
    cur = conn.execute("INSERT INTO holds (machine_id, kind, held_at, said, until) VALUES (?,?,?,?,?)",
                       (ms.remember_machine(conn), _scope(scope), now, said, until))
    conn.commit()
    return dict(conn.execute("SELECT * FROM holds WHERE id = ?", (cur.lastrowid,)).fetchone())


def release(conn, now: float | None = None, scope: str | None = None) -> dict | None:
    """End every `scope` hold in force now (no scope: the only one in force, refused when several are); the latest."""
    now = time.time() if now is None else now
    if scope is None:
        held = actives(conn, now)
        if len(held) > 1:
            raise ValueError(f"{' and '.join(h['kind'] for h in held)} are both held; "
                             f"say which: {RELEASE} {held[0]['kind']}")
        if not held:
            return None
        scope = held[0]["kind"]
    got = active(conn, now, _scope(scope))
    if got is None:
        return None
    if scope == GPU:
        _legacy_path().unlink(missing_ok=True)
    if _has(conn):
        where, args = _here(conn)
        conn.execute(f"UPDATE holds SET released_at = ? WHERE {where} AND kind = ? AND released_at IS NULL "
                     "AND (until IS NULL OR until > ?)", (now, *args, scope, now))
        conn.commit()
    return {**got, "released_at": now}


def _at(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def line(h: dict, now: float | None = None) -> str:
    """One line on a hold: its scope, since when, who and why, and until when."""
    now = time.time() if now is None else now
    scope = h.get("kind") or BENCHMARKS
    if h.get("released_at") is not None:
        state = f", released {_at(h['released_at'])}"
    elif h.get("until") is not None:
        state = f", {'ended' if h['until'] <= now else 'until'} {_at(h['until'])}"
    else:
        state = f", until {RELEASE} {scope}"
    return f"{scope} held since {_at(h['held_at'])}{state}: {h['said']}"


def held(conn=None, now: float | None = None, scope: str = BENCHMARKS) -> str:
    """The line of the `scope` hold in force, '' when none is."""
    from harness import workqueue as wq
    with wq._store(conn) as c:
        h = active(c, now, scope)
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
    """Whether the owner let this job start through a benchmark hold."""
    r = conn.execute("SELECT despite_hold FROM jobs WHERE id = ?", (_key(job),)).fetchone()
    return bool(r and r["despite_hold"])


def let(conn, job_id) -> None:
    """Let one pending job start through a benchmark hold."""
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
