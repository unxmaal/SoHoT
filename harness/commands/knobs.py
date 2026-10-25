"""`soh knobs backlog`: the unregistered gating sites, what a branch added, and their burn-down order by binding evidence. #1085."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, note

DAY = 86400.0


def add_parser(sub) -> None:
    p = sub.add_parser("knobs", help="the knob backlog: unregistered gating sites, the ones this branch added, "
                       "and with --by-binding how often a stored reason quotes each one's limit")
    p.add_argument("action", choices=("backlog", "engine-timeouts"),
                   help="backlog, or engine-timeouts: each engine's slowest finished case per machine, the clock "
                        "derived from it and how many stored cases each margin would have cut (#708)")
    p.add_argument("--by-binding", action="store_true",
                   help="rank the sites by waiting, skipped and declined verdicts a reason quoting them wrote")
    p.add_argument("--store", default="", help="a discovery.db to read read-only (default: a copy of this home's)")
    p.add_argument("--days", type=float, default=None, help="only verdicts of the last N days (default: all)")
    p.add_argument("--base", default="", help="the branch the added sites are counted against (default: origin/main)")
    p.add_argument("-n", type=int, default=20, help="with --by-binding, how many sites to list")
    p.set_defaults(func=cmd_knobs)


def _connect(store: str):
    from harness import ledger, morning
    if not store:
        return morning.snapshot()
    from pathlib import Path
    if not Path(store).is_file():
        raise FileNotFoundError(f"no store at {store}")
    return ledger.open_ro(Path(store))


def cmd_engine_timeouts(a) -> int:
    from harness import engine_timeout as et
    try:
        conn = _connect(a.store)
    except (OSError, FileNotFoundError) as exc:
        return err(str(exc))
    try:
        rows = et.backtest(conn)
        boards = {r[0]: r[1] for r in conn.execute("SELECT id, hw_model FROM machines")}
    finally:
        conn.close()
    note(f"margin {et.MARGIN:g}, floor {et.FLOOR_S:g}s, {et.MIN_CASES} finished cases needed; cut = stored cases a "
         f"clock set from the cases before them would have stopped")
    note(f"\n{'lane':<10} {'engine':<18} {'machine':<12} {'cases':>6} {'slowest':>9} {'clock':>8}  "
         + "  ".join(f"cut@{m:g}" for m in et.MARGINS))
    for r in rows:
        clock = f"{r['seconds']:g}" if r["seconds"] else "ceiling"
        note(f"{r['lane']:<10} {r['engine']:<18} {str(boards.get(r['machine_id'], r['machine_id'])):<12} "
             f"{r['cases']:>6} {r['slowest']:>9.1f} {clock:>8}  " + "  ".join(f"{r['cut'][m]:>6}" for m in et.MARGINS))
    emit(margin=et.MARGIN, floor_s=et.FLOOR_S, min_cases=et.MIN_CASES,
         engines=[{**r, "cut": {f"{m:g}": n for m, n in r["cut"].items()}} for r in rows])
    return 0


def cmd_knobs(a) -> int:
    if a.action == "engine-timeouts":
        return cmd_engine_timeouts(a)
    from harness import knob_backlog as kb
    base = a.base or kb.BASE
    sites = kb.sites()
    added = kb.added(base=base)
    note(f"{len(sites)} site(s) in {kb.DIR}")
    if added is None:
        note(f"  {base} is not in this clone; added sites not counted")
    else:
        note(f"  {len(added)} added since the merge base with {base}" + "".join(f"\n    {s}" for s in added))
    if not a.by_binding:
        emit(sites=sites, added=added, base=base)
        return 0
    try:
        conn = _connect(a.store)
    except (OSError, FileNotFoundError) as exc:
        return err(str(exc))
    since = time.time() - a.days * DAY if a.days else None
    try:
        rows = kb.by_binding(conn, since=since)
    finally:
        conn.close()
    note(f"\n{'hits':>5} {'quotes':>6}  site: example")
    for r in rows[:a.n]:
        note(f"{r['hits']:>5} {len(r['quotes']):>6}  {r['site']}" + (f": {r['example']}" if r["example"] else ""))
    quoted = sum(1 for r in rows if r["quotes"])
    note(f"\n{quoted} of {len(rows)} site(s) are quoted by a reason; {sum(1 for r in rows if r['hits'])} bound a verdict")
    emit(sites=sites, added=added, base=base, by_binding=rows, since=since)
    return 0
