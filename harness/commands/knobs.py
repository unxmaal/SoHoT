"""`soh knobs backlog`: the unregistered gating sites, what a branch added, and their burn-down order by binding evidence. #1085."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, note

DAY = 86400.0


def add_parser(sub) -> None:
    p = sub.add_parser("knobs", help="the knob backlog: unregistered gating sites, the ones this branch added, "
                       "and with --by-binding how often a stored reason quotes each one's limit")
    p.add_argument("action", choices=("backlog",))
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


def cmd_knobs(a) -> int:
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
