"""No repo is downloaded again within a day unless a verdict was written since; a refused refetch is a needs-you mark (#2161)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness import cuts, machine_scope

REFETCH_WINDOW_S = 86400.0
GIB = float(1 << 30)
FILE = "refetch-blocked.json"
CONFIRMED_FILE = "confirm-refetched.json"
#: The `via` of a held win's confirmation fetch is "confirm <verdict id>"; it may refetch once. #2201.
CONFIRM_VIA = "confirm "
#: The words of a refusal that no job can wait out: it is the same when the job would run again. #2201.
NOT_AGAIN = "so it is not downloaded again within"
#: The event of the fetch verdict that records a download: it follows every download, so it is no answer about the weights.
LANDED_EVENT = "downloaded"
#: The event of the fetch verdict that says a dependency is not here yet: no answer about the weights either.
WAITING_EVENT = "waiting"
WAITING = "waiting on "
#: The verdict outcomes that settle a candidate; discovery_flow.wasted reads the same set, a queued verdict is no decision. #2174.
DECIDED = ("declined", "broken", "measured", "adopted")
#: A screen that passed moves the candidate on: it lifts the refetch block, though a removal under it is still waste.
LIFTS = ("screened",) + DECIDED
_WHOLE = "(%s.complete = 1 OR %s.state IN ('complete', 'removed'))"


def path() -> Path:
    from harness import paths
    return paths.home() / FILE


def confirm_path() -> Path:
    from harness import paths
    return paths.home() / CONFIRMED_FILE


def _confirmed() -> dict:
    try:
        body = json.loads(confirm_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _confirm_leave(conn, repo: str, via: str, owner: str) -> int | None:
    """The held verdict whose confirmation may refetch `repo` once, else None. #2201."""
    if not via.startswith(CONFIRM_VIA) or not via[len(CONFIRM_VIA):].isdigit():
        return None
    vid = int(via[len(CONFIRM_VIA):])
    if str(vid) in _confirmed():
        return None
    names = sorted({n for n in (repo, owner) if n})
    marks = ",".join("?" * len(names))
    got = conn.execute(f"SELECT 1 FROM verdicts v JOIN proposals p ON p.id = v.proposal_id WHERE v.id = ? AND v.failure_class = ? "
                       f"AND p.state_verdict_id = v.id AND (p.name IN ({marks}) OR p.resolved IN ({marks}))",
                       (vid, "confirming", *names, *names)).fetchone()
    return vid if got else None


def _read_all() -> dict:
    try:
        body = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"?": {"via": "", "why": "unreadable mark file", "at": 0}}
    return body if isinstance(body, dict) else {"?": {"via": "", "why": "unreadable mark file", "at": 0}}


def read(now: float | None = None) -> dict:
    """{repo: {"via", "why", "at"}} for each refetch refused within the window: past it the repo may be fetched again."""
    now = time.time() if now is None else now
    return {k: v for k, v in _read_all().items() if k == "?" or now - float(v.get("at") or 0) <= REFETCH_WINDOW_S}


def mark(repo: str, via: str, why: str, now: float | None = None) -> None:
    """Record that a download of `repo` by `via` was refused."""
    got = {k: v for k, v in read(now).items() if k != "?"}
    got[repo] = {"via": via, "why": why[:300], "at": time.time() if now is None else now}
    to = path()
    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")


def clear(repo: str) -> None:
    """`repo` was downloaded with the budget's leave: drop its mark."""
    got = _read_all()
    if got.pop(repo, None) is not None and "?" not in got:
        path().write_text(json.dumps(got, sort_keys=True), encoding="utf-8")


def _last(conn, repo: str, now: float) -> dict | None:
    here, mine = machine_scope.here(conn, "downloads.mine")
    row = conn.execute(f"SELECT MAX(started_at) AS at, MAX(bytes) AS bytes FROM downloads d WHERE repo = ? AND bytes > 0 "
                       f"AND started_at >= ? AND {_WHOLE % ('d', 'd')} AND {here}",
                       (repo, now - REFETCH_WINDOW_S, *mine)).fetchone()
    return {"bytes": int(row["bytes"]), "started_at": float(row["at"])} if row and row["at"] is not None else None


def _verdict_since(conn, names: set, since: float) -> bool:
    marks = ",".join("?" * len(names))
    got = conn.execute(f"SELECT 1 FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                       f"WHERE (p.name IN ({marks}) OR p.resolved IN ({marks})) AND v.decided_at > ? AND v.outcome IN ({','.join('?' * len(LIFTS))}) LIMIT 1",
                       (*sorted(names), *sorted(names), since, *LIFTS)).fetchone()
    return got is not None


def _cut_short(conn, names: set, last: dict) -> bool:
    """The job that ran this download ended cancelled or failed, and no verdict but the landing marks followed it: the screen never got to say anything. #2188."""
    from harness import job_state, machine_scope
    here, mine = machine_scope.here(conn, "jobs.claimed")
    at = last["started_at"]
    ended = conn.execute(f"SELECT 1 FROM jobs WHERE state IN (?, ?) AND started_at <= ? AND finished_at >= ? AND {here} LIMIT 1",
                         (job_state.CANCELLED, job_state.FAILED, at, at, *mine)).fetchone()
    if ended is None:
        return False
    marks = ",".join("?" * len(names))
    spoke = conn.execute(f"SELECT 1 FROM verdicts v JOIN proposals p ON p.id = v.proposal_id WHERE (p.name IN ({marks}) OR p.resolved IN ({marks})) "
                         f"AND v.decided_at > ? AND v.event NOT IN (?, ?) LIMIT 1",
                         (*sorted(names), *sorted(names), at, LANDED_EVENT, WAITING_EVENT)).fetchone()
    return spoke is None


def holds(conn, repo: str, via: str, owner: str = "", now: float | None = None) -> str:
    """Why `repo` may not be downloaded again now, "" when it may: it landed within the window and no verdict that decided it was written since. #2161, #2165."""
    now = time.time() if now is None else now
    last = _last(conn, repo, now)
    names = {n for n in (repo, owner) if n}
    if last is None or _verdict_since(conn, names, last["started_at"]) or _cut_short(conn, names, last):
        return ""
    return (f"{repo} was downloaded {(now - last['started_at']) / 3600:.1f} h ago ({last['bytes'] / GIB:.1f} GiB) and no verdict "
            f"was written since, {NOT_AGAIN} {REFETCH_WINDOW_S / 3600:g} h (asked for by {via})")


def refusal(conn, repo: str, via: str, owner: str = "", now: float | None = None) -> str:
    """`holds`, and a refusal is a recorded cut and marked for a person. #2161."""
    now = time.time() if now is None else now
    why = holds(conn, repo, via, owner, now)
    vid = _confirm_leave(conn, repo, via, owner) if why else None
    if vid is not None:
        # A held win is tested near-immediately and its weights are gone by the confirmation: one refetch, then the guard stands. #2201.
        confirm_path().write_text(json.dumps({**_confirmed(), str(vid): now}, sort_keys=True), encoding="utf-8")
        return ""
    if why:
        cuts.cut("refetch_window", why, value=REFETCH_WINDOW_S, kept=0, dropped=1, conn=conn)
        mark(repo, via, why, now)
    return why


def redone(conn, now: float | None = None) -> dict:
    """What the last window downloaded of repos this machine had already downloaded: {"gib", "n", "repos"}. #2161."""
    now = time.time() if now is None else now
    here, mine = machine_scope.here(conn, "downloads.mine", "d.machine_id")
    rows = conn.execute(
        f"SELECT d.repo, d.bytes FROM downloads d WHERE d.bytes > 0 AND d.started_at >= ? AND {_WHOLE % ('d', 'd')} AND {here} "
        f"AND EXISTS (SELECT 1 FROM downloads e WHERE e.repo = d.repo AND e.id < d.id AND e.bytes > 0 "
        f"AND e.machine_id = d.machine_id AND {_WHOLE % ('e', 'e')})",
        (now - REFETCH_WINDOW_S, *mine)).fetchall()
    return {"gib": round(sum(int(r["bytes"]) for r in rows) / GIB, 1), "n": len(rows), "repos": len({r["repo"] for r in rows})}


def refused(conn, now: float | None = None) -> dict:
    """The repos refused a second download within the window, with what each landed: {"n", "gib", "rows"}. #2188."""
    now = time.time() if now is None else now
    rows = []
    for repo, v in sorted(read(now).items()):
        last = _last(conn, repo, now) if repo != "?" else None
        rows.append({"repo": repo, "via": v.get("via") or "", "why": v.get("why") or "", "at": v.get("at"),
                     "gib": round(last["bytes"] / GIB, 1) if last else 0.0})
    return {"n": len(rows), "gib": round(sum(r["gib"] for r in rows), 1), "rows": rows}
