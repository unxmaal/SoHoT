"""`soh lane-gate status|open|close`: the lanes the power gate closes to challengers, and the owner's recorded, expiring override (#2164)."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, lent_store, note


def add_parser(sub) -> None:
    p = sub.add_parser("lane-gate", help="the lanes whose holdout cannot reach lane_gate_power at their adopt effect "
                       "take no challengers; open one anyway for a while, or close it again")
    p.add_argument("action", choices=("status", "open", "close", "replay"))
    p.add_argument("lane", nargs="?", default="", help="the lane to open or close, or replay")
    p.add_argument("--incumbent", default="", help="replay: the incumbent's receipt key (default: the served one)")
    p.add_argument("--challenger", action="append", default=[], help="replay: a challenger's key (default: every stored one)")
    p.add_argument("--also", action="append", default=[], help="replay: a store copy whose rows join the live store's, read only")
    p.add_argument("--reps", type=int, default=200, help="replay: bootstrap draws per holdout size")
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
    if a.action == "replay":
        return _replay(a)
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


def _replay(a) -> int:
    """Stored pairs of a WER/CER lane under the pass/fail sign test, the sign test on the metric and the signed-rank test (#2181)."""
    from harness import continuous, holdout, lane_gate, lanes, store
    lane = lanes.canonical(a.lane)
    if not continuous.metric_of(lane):
        return err(f"{lane} is not scored on an error rate; lanes that are: {', '.join(sorted(continuous.METRIC))}")
    with lent_store() as conn:
        rows = continuous.stored_rows(conn, lane)
        key = a.incumbent or lane_gate.profile(lane, {}, conn)[0]
    for path in a.also:
        extra = store.open_ro(path)
        try:
            rows += continuous.stored_rows(extra, lane)
        finally:
            extra.close()
    got = continuous.replays(rows, lane, key, a.challenger, reps=a.reps)
    note(f"{lane} holdout {len(holdout.for_lane(lane).holdout)}, {key} as incumbent; holdout cases for power 0.8 by bootstrap, "
         f"p observed; sign_pass = the old pass/fail test, sign_metric = signs of the {continuous.metric_of(lane)} drop")
    for r in got:
        if not r["cases"]:
            continue
        need = " ".join(f"{k} {r['cases_needed'][k] or '>%d' % continuous.GRID[-1]}" for k in continuous.TESTS)
        p = " ".join(f"{k} {r['p'][k]:.3g}" for k in continuous.TESTS)
        note(f"  {'control' if r['control'] else r['challenger']:42} {r['cases']} cases, drop {r['shift']:+.4f}  p: {p}  needs: {need}")
    emit(lane=lane, incumbent=key, pairs=got)
    return 0
