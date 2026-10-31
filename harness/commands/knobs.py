"""`soh knobs backlog`: the unregistered gating sites, what a branch added, and their burn-down order by binding evidence. #1085."""
from __future__ import annotations

import time

from harness.commands.common import emit, err, note

DAY = 86400.0


def add_parser(sub) -> None:
    p = sub.add_parser("knobs", help="the knob backlog: unregistered gating sites, the ones this branch added, "
                       "and with --by-binding how often a stored reason quotes each one's limit")
    p.add_argument("action", choices=("backlog", "effects", "engine-timeouts", "reply-caps"),
                   help="backlog; effects: each lane's same-config rerun churn, the adopt effect derived from it "
                        "against the registered one, and every stored adopt verdict replayed under it (#725); or "
                        "engine-timeouts: each engine's slowest finished case per machine, the clock derived from "
                        "it and how many stored cases each margin would have cut (#708); or reply-caps: each "
                        "lane-model's derived reply budget, where it came from and what it keeps and saves on "
                        "its stored rows (#1352)")
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


def cmd_effects(a) -> int:
    from harness import effects, power
    try:
        conn = _connect(a.store)
    except (OSError, FileNotFoundError) as exc:
        return err(str(exc))
    try:
        # A store named on the command line is someone's copy; this home's cut log is not its record.
        derived = effects.derive(conn, record=not a.store)
        want = {lane: d["effect"] for lane, d in derived.items() if d["effect"] is not None}
        replayed = effects.replay(conn, want)
    finally:
        conn.close()
    note(f"noise = the share of cells a same-config rerun flips each way, rounded up to 0.01, never under "
         f"{effects.FLOOR:g}; under {effects.MIN_CASES} cases measured twice keeps {power.DEFAULT_EFFECT:g}; "
         f"the gate powers for max(noise, adopt_min_effect {power.MIN_EFFECT:g})")
    note(f"\n{'lane':<10} {'configs':>7} {'cases':>6} {'churn':>7} {'derived':>8} {'registered':>10} {'used':>5}")
    drift = []
    for lane, d in derived.items():
        churn = "-" if d["churn"] is None else f"{d['churn']:.4f}"
        got = power.noise_for(lane)
        if (d["effect"] if d["effect"] is not None else power.DEFAULT_EFFECT) != got:
            drift.append(lane)
        note(f"{lane:<10} {d['configs']:>7} {d['cases']:>6} {churn:>7} "
             f"{'-' if d['effect'] is None else format(d['effect'], '.2f'):>8} {got:>10.2f} "
             f"{power.effect_for(lane):>5.2f}" + ("  differs" if lane in drift else ""))
    changed = [r for r in replayed if r["replayed"] != r["stored"] or r["under_noise"] != r["replayed"]]
    floored = [r for r in changed if r["under_noise"] != r["replayed"]]
    note(f"\nreplay: {len(replayed)} adopt verdict(s), {len(changed)} change under the used effects and the dev "
         f"confirmation or differ from the noise effect alone, {len(floored)} because of adopt_min_effect")
    for r in changed:
        note(f"  {r['id']:>6} {r['lane']:<9} {r['stored']} -> {r['replayed']} (noise alone: {r['under_noise']}, "
             f"+{r['noise']:.2f} -> +{r['effect']:.2f}): {r['why']}")
    emit(floor=effects.FLOOR, min_cases=effects.MIN_CASES, min_effect=power.MIN_EFFECT, lanes=derived, drift=drift,
         replay=replayed)
    return 0


def cmd_reply_caps(a) -> int:
    from harness import reply_cap as rc
    try:
        conn = _connect(a.store)
    except (OSError, FileNotFoundError) as exc:
        return err(str(exc))
    try:
        rows = rc.report(conn)
    finally:
        conn.close()
    note(f"quantile {rc.QUANTILE:g} of a model's passing replies' tokens plus {rc.MARGIN:g}, in steps of {rc.STEP}, "
         f"or its budget sweep within {rc.NOISE_Z:g} sd of the best; {rc.MIN_PASSES} passes needed; kept, lost and "
         f"saved re-score its rows at the lane's whole budget")
    for r in rows:
        note(f"{r['lane']:<8} {r['model'][:44]:<44} {rc.said(r)}; {r['kept']} kept, {r['lost']} lost, "
             f"{r['saved_share']:.0%} of {r['seconds'] / 3600:.1f} h saved")
    emit(quantile=rc.QUANTILE, margin=rc.MARGIN, step=rc.STEP, min_passes=rc.MIN_PASSES, noise_z=rc.NOISE_Z, caps=rows)
    return 0


def cmd_knobs(a) -> int:
    if a.action == "reply-caps":
        return cmd_reply_caps(a)
    if a.action == "engine-timeouts":
        return cmd_engine_timeouts(a)
    if a.action == "effects":
        return cmd_effects(a)
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
    from harness import memory_store as ms
    try:
        with ms.lend(conn):  # its cuts are about the report, never this home's store. #1432.
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
