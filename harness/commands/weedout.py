"""`soh weedout-replay`: every stored paired run and planted challengers through today's looks and the weed-out order, read-only (#1439)."""
from __future__ import annotations

from harness.commands.common import emit, note


def cmd_weedout_replay(a) -> int:
    from collections import Counter

    from harness import weedout_replay
    from harness import memory_store as ms
    from harness.commands.measure_order import _open
    conn = _open(a.store)
    try:
        with ms.lend(conn):
            got = weedout_replay.replay(conn, a.lane, alpha=a.alpha)
            lines = weedout_replay.replay_lines(got)
            sim = {}
            inc = a.incumbent or (Counter(x["inc"] for x in got).most_common(1) or [("", 0)])[0][0]
            if a.simulate and inc:
                sim = weedout_replay.simulate(conn, a.lane, inc, reps=a.simulate, blocks=a.blocks, alpha=a.alpha,
                                              seed=a.seed)
                lines.append(f"planted around {inc} on the {a.lane} holdout, {a.blocks} x {a.simulate} per effect:")
                lines += weedout_replay.simulate_lines(sim)
    finally:
        conn.close()
    for line in lines:
        note(line)
    emit(lines=lines, simulate=sim)
    return 0


def add_parser(sub) -> None:
    from harness import adopt
    p = sub.add_parser("weedout-replay", help="replay every stored paired run of a lane under today's looks and the "
                       "weed-out order, and plant challengers of known effect; read-only (#1439)")
    p.add_argument("--lane", default="code", help="the lane (default code)")
    p.add_argument("--store", default="", help="a copy of the store to read instead of the live one, for every read")
    p.add_argument("--alpha", type=float, default=adopt.ALPHA, help=f"the gate's level (default {adopt.ALPHA})")
    p.add_argument("--simulate", type=int, default=0, metavar="REPS",
                   help="also plant challengers (equal, +5, +10, -5 points): REPS replicates per block and effect")
    p.add_argument("--blocks", type=int, default=4, help="halvings of the incumbent's runs the simulation draws")
    p.add_argument("--incumbent", default="", help="the incumbent receipt key to plant around (default the lane's)")
    p.add_argument("--seed", type=int, default=1439, help="the simulation's seed")
    p.set_defaults(func=cmd_weedout_replay)
