"""`soh families`: each lineage root's paired record per lane, the queue with and without the family term, tonight's measure plan with and without the diversity slot; from a copy of the store. #1100, #1111."""
from __future__ import annotations

import statistics
import time

from harness.commands.common import emit, note

DAY = 86400.0


def records(st) -> list[dict]:
    """Every family with a paired comparison, by lane, most losses first."""
    return [{"lane": f.lane, "family": f.key, "root": f.root, "losses": len(f.lost), "lost": list(f.lost),
             "verdicts": f.verdicts, "won": f.won, "last_compared": f.last_compared, "demoted": f.demoted}
            for f in sorted(st.families.values(), key=lambda f: (f.lane, -len(f.lost), f.key))]


def queue(conn, st, lane: str) -> list[dict]:
    """The lane's ranked queue with the family term, each row's place without it beside its place with it."""
    from harness import family, rank, report
    rows = report.ms_judgeable(conn)
    kw = dict(serving=rank.serving(), measured_lanes=rank.lanes_with_receipts(conn), conn=conn)
    before = [r["name"] for r in rank.rank(rows, standing=family.Standing(), **kw) if rank.lane_of(r) == lane]
    after = [r for r in rank.rank(rows, standing=st, **kw) if rank.lane_of(r) == lane]
    was = {n: i + 1 for i, n in enumerate(before)}
    return [{"name": r["name"], "at": i + 1, "was": was.get(r["name"]), "value": r["value"],
             "family": st.key_of(r), "why": r["value_why"]} for i, r in enumerate(after)]


def per_night(conn, now: float, nights: int) -> float:
    """Median measure runs recorded per night over the last `nights` nights, 0 when none."""
    got = [0] * nights
    for (at,) in conn.execute("SELECT recorded_at FROM runs WHERE tier = 'measure' AND recorded_at >= ?",
                              (now - nights * DAY,)):
        got[min(int((now - float(at)) // DAY), nights - 1)] += 1
    return statistics.median(got) if got else 0.0


def tonight(conn, st, lane: str, n: float) -> dict:
    """The measure queue as the sweep builds it, with the diversity slot and without; memory is not checked."""
    from harness.commands import loop
    said: list[str] = []
    unchecked = lambda row: (True, None, "not checked in a dry run")  # noqa: E731
    with_slot = loop.measure_queue(conn, lane, 0, room=unchecked, say=said.append)
    without = loop.measure_queue(conn, lane, 0, room=unchecked, slots=0, say=lambda line: None)
    return {"n": n, "with": [r["name"] for r in with_slot], "without": [r["name"] for r in without],
            "lines": [ln.strip() for ln in said], "families": {r["name"]: st.key_of(r) for r in with_slot}}


def render(r: dict, head: int) -> list[str]:
    from harness import family
    out = [f"paired record per lineage root (demoted at {r['losses_to_demote']} members lost since the last win; "
           f"demotion {family.DEMOTION:+g})"]
    for f in r["records"]:
        flag = "DEMOTED" if f["demoted"] else ""
        out.append(f"  {f['lane']:<7} {f['family'][:40]:<40} lost {f['losses']} of {f['verdicts']} verdict(s)"
                   f"{', won by ' + f['won'] if f['won'] else ''} {flag}".rstrip())
    out.append(f"\n{r['lane']}-lane queue, head {head}: place with the family term (place without it)")
    termed = [q for q in r["queue"] if "family lost at the paired gate" in q["why"]]
    for q in r["queue"][:head]:
        out.append(f"  #{q['at']:<4} ({q['was']}) {q['value']:+6.2f} {q['name'][:56]:<56} [{q['family'][:28]}]")
    out.append(f"  {len(termed)} of {len(r['queue'])} row(s) take the family term")
    for q in [q for q in r["queue"] if "family" in q["why"] and ("lost at the paired gate" in q["why"]
                                                               or "exempt" in q["why"])][:head]:
        out.append(f"  #{q['at']} ({q['was']}) {q['name']}: "
                   + "; ".join(w for w in q["why"].split("; ") if "family" in w))
    t = r["tonight"]
    out.append(f"\ntonight's {r['plan_lane'] or 'all-lane'} measure plan, about {t['n']:g} measurement(s) a night "
               f"(median of the last {r['nights']} nights); a row past that waits for the next sweep")
    for label, names in (("with the diversity slot", t["with"]), ("without it", t["without"])):
        out.append(f"  {label}:")
        for i, name in enumerate(names):
            mark = "*" if i < t["n"] else " "
            out.append(f"   {mark}{i + 1:>3} {name[:60]:<60} [{t['families'].get(name, '')[:28]}]")
    out.extend(f"  {ln}" for ln in t["lines"])
    out.append("  (a dry run checks no memory: the sweep gives a slot back when its pick does not fit)")
    return out


def cmd_families(a) -> int:
    from harness import family, morning
    now = time.time()
    lane = (a.lane or "").strip().lower()
    # A what-if for this process only, the way `--knob` rebinds a site for one run.
    for attr, got in (("LOSSES_TO_DEMOTE", a.losses), ("WINDOW_DAYS", a.window_days), ("SLOTS", a.slots),
                      ("DEMOTION", a.demotion)):
        if got is not None:
            setattr(family, attr, got)
    conn = morning.snapshot()
    try:
        st = family.standing(conn)
        r = {"generated": now, "lane": lane, "plan_lane": a.plan_lane, "losses_to_demote": st.losses_to_demote,
             "window_days": family.WINDOW_DAYS, "slots": family.SLOTS,
             "demotion": family.DEMOTION, "nights": a.nights,
             "records": records(st), "queue": queue(conn, st, lane) if lane else [],
             "tonight": tonight(conn, st, a.plan_lane, per_night(conn, now, a.nights))}
    finally:
        conn.close()
    for ln in render(r, a.head):
        note(ln)
    emit(**r)
    return 0
