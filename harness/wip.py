"""Per-lane measure WIP: screened, paused and running measures against measure_wip, and how many screens a lane may pull (#2165)."""
from __future__ import annotations

import json

from harness import lanes, machine_scope

#: Most screened, paused and running measures one open lane holds before its next candidate waits unscreened. #2165.
LIMIT = 2


def _challenger(argv: list) -> tuple[str, str]:
    """(lane, challenger) of an adopt run's argv, ('', '') for any other job."""
    if "adopt" not in argv or "--challenger" not in argv:
        return "", ""
    lane = argv[argv.index("--lane") + 1] if "--lane" in argv[:-1] else ""
    at = argv.index("--challenger")
    return lanes.canonical(lane), argv[at + 1] if at + 1 < len(argv) else ""


def used(conn) -> dict[str, list[str]]:
    """Each lane's measures in hand: screened candidates waiting, paused runs and running adopts, a name once."""
    from harness import paused
    held: dict[str, dict[str, None]] = {}

    def add(lane, name):
        if lane and name:
            held.setdefault(lanes.canonical(lane), {})[name] = None
    for r in conn.execute("SELECT name, lane FROM proposals WHERE state = 'screened'"):
        add(r["lane"], r["name"])
    for p in paused.waiting(conn):
        add(p["lane"], p["proposal"] or p["challenger"])
    here, mine = machine_scope.here(conn, "jobs.claimed")
    for j in conn.execute(f"SELECT argv FROM jobs WHERE state = 'running' AND {here}", mine):
        try:
            argv = json.loads(j["argv"] or "[]")
        except ValueError:
            continue
        add(*_challenger(argv if isinstance(argv, list) else []))
    return {lane: list(names) for lane, names in held.items()}


class Pulled(list):
    """The rows a lane's room pulls, in order; `backfill` hands out the next held row of a lane whose pull did not stay in hand."""
    held: dict

    def backfill(self, row: dict, lane_of=None) -> dict | None:
        lane_of = lane_of or _lane_of
        queue = self.held.get(lanes.canonical(lane_of(row)))
        return queue.pop(0) if queue else None


def _lane_of(r: dict) -> str:
    return lanes.canonical(r.get("modality") or r.get("lane") or "")


def pull(conn, rows: list[dict], lane_of=None, say=None) -> Pulled:
    """`rows` in their order, each lane's first `LIMIT - used` of them; the rest wait, a recorded cut."""
    from harness import cuts
    lane_of = lane_of or _lane_of
    have = used(conn)
    room = {lane: LIMIT - len(names) for lane, names in have.items()}
    kept, held = Pulled(), {}
    for r in rows:
        lane = lanes.canonical(lane_of(r))
        left = room.setdefault(lane, LIMIT)
        if left > 0:
            room[lane] = left - 1
            kept.append(r)
        else:
            held.setdefault(lane, []).append(r)
    kept.held = held
    for lane, waiting in held.items():
        said = f"{lane}: {len(waiting)} candidate(s) wait unscreened, {len(have.get(lane, []))} of {LIMIT} measures in hand"
        cuts.cut("measure_wip", said, value=LIMIT, kept=sum(1 for r in kept if lanes.canonical(lane_of(r)) == lane),
                 dropped=len(waiting), conn=conn)
        if say:
            say(f"  {said}")
    return kept


def share_until(cap: float | None, now: float, pulls: int, per_s: float) -> float | None:
    """The time a screen step may run to: what `pulls` screens need and one more screen's margin, never past `cap`."""
    if cap is None or per_s <= 0:
        return cap
    return min(cap, now + (pulls + 1) * per_s)


def status(conn) -> list[dict]:
    """Each lane holding or waiting on a measure: {lane, used, limit, names, closed}, the gate's closed lanes marked."""
    from harness import lane_gate
    have = used(conn)
    waiting = {lanes.canonical(r["lane"]) for r in conn.execute("SELECT lane FROM proposals WHERE state = 'queued'")}
    every = sorted((set(have) | waiting) - {""})
    closed = set(lane_gate.shut(conn, every))
    return [{"lane": lane, "used": len(have.get(lane, [])), "limit": LIMIT, "names": have.get(lane, []),
             "closed": lane in closed} for lane in every if have.get(lane) or lane not in closed]
