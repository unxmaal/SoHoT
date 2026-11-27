"""`soh yield`: GPU hours and GiB per decided verdict and per adoption, per lane, from a copy of the store (#2163)."""
from __future__ import annotations

import time

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    p = sub.add_parser("yield", help="GPU hours and GiB per decided verdict and per adoption, per lane, over 7 and 30 days; "
                       "read from a copy of the store")
    p.add_argument("--lane", default="", help="only this lane")
    p.add_argument("--days", type=int, default=0, help="one window of this many days (default: 7 and 30)")
    p.set_defaults(func=cmd_pipeline_yield)


def cmd_pipeline_yield(a) -> int:
    from harness import morning, pipeline_yield
    now = time.time()
    days = (a.days,) if a.days and a.days > 0 else pipeline_yield.WINDOWS
    conn = morning.snapshot()
    try:
        r = pipeline_yield.gather(conn, now, days, (a.lane or "").strip().lower())
    finally:
        conn.close()
    for ln in pipeline_yield.render(r):
        note(ln)
    emit(**r)
    return 0
