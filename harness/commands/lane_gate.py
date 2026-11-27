"""`soh lane-gate status|open|close`: the lanes the power gate closes to challengers, and the owner's recorded, expiring override (#2164)."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, lent_store, note


def add_parser(sub) -> None:
    p = sub.add_parser("lane-gate", help="the lanes whose holdout cannot reach lane_gate_power at their adopt effect "
                       "take no challengers; open one anyway for a while, or close it again")
    p.add_argument("action", choices=("status", "open", "close"))
    p.add_argument("lane", nargs="?", default="", help="the lane to open or close")
    p.set_defaults(func=cmd_lane_gate)


def _at(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def cmd_lane_gate(a) -> int:
    from harness import lane_gate
    from harness import memory_store as ms
    if a.action == "status":
        with lent_store() as conn:
            got = lane_gate.status(conn)
        for g in got["closed"]:
            note(g["why"])
        for g in got["opened"]:
            note(f"{g['lane']} is open anyway until {_at(g['until'])}: {g['said']}")
        if not got["closed"] and not got["opened"]:
            note(f"no lane is under lane_gate_power {got['threshold']:.2f}")
        emit(**got)
        return 0
    if not a.lane:
        return err(f"soh lane-gate {a.action} names a lane")
    conn = ms.connect()
    try:
        if a.action == "open":
            try:
                got = lane_gate.open_lane(conn, a.lane)
            except ValueError as exc:
                return err(str(exc))
            note(f"{a.lane} is open to challengers until {_at(got['until'])}: {got['said']}")
        else:
            got = lane_gate.close_lane(conn, a.lane)
            note(f"{a.lane} takes no challengers again" if got else f"{a.lane} had no override in force")
    finally:
        conn.close()
    emit(lane=a.lane, action=a.action, override=got)
    return 0
