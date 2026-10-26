"""`soh measure-order`: today's measure queue by expected gain per GPU-minute, or a replay of past nights, read-only (#1315)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.commands.common import emit, note


def _open(store: str):
    from harness import ledger
    from harness import memory_store as ms
    if store:
        conn = sqlite3.connect(f"{Path(store).resolve().as_uri()}?immutable=1", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    return ledger.open_ro(ms.db_path())


def cmd_measure_order(a) -> int:
    from harness import measure_replay
    conn = _open(a.store)
    try:
        if a.replay:
            lines = measure_replay.report(conn, int(a.replay), want=a.lane, head=a.head)
        else:
            lines = measure_replay.today(conn, want=a.lane, head=a.head)
    finally:
        conn.close()
    for line in lines:
        note(line)
    emit(lines=lines)
    return 0


def add_parser(sub) -> None:
    p = sub.add_parser("measure-order", help="the measure queue by expected gain per GPU-minute with each key, or "
                       "--replay DAYS of past nights against their ceiling; read-only (#1315)")
    p.add_argument("--lane", default="", help="the lane the sweep is scoped to, as `discover --lane` (default every lane)")
    p.add_argument("--store", default="", help="a copy of the store to read instead of the live one")
    p.add_argument("--replay", type=int, default=0, metavar="DAYS",
                   help="replay the last DAYS nights: the queue each faced, in survivors order and by gain")
    p.add_argument("--head", type=int, default=5, help="rows per order to list (0 is all, without --replay)")
    p.set_defaults(func=cmd_measure_order)
