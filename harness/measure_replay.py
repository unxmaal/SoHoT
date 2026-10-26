"""Each night's measure queue rebuilt from the store as of that night, in survivors order and by gain, walked against its ceiling (#1315)."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from harness import measure_gain, power
from harness import memory_store as ms

DAY = 86400.0
_START = re.compile(r"(\d{8}-\d{6})-adopt-")


def started_at(path: str) -> float | None:
    """When a measurement began, from its out dir's name; None for a path no measure step wrote."""
    m = _START.search(path or "")
    return time.mktime(time.strptime(m.group(1), "%Y%m%d-%H%M%S")) if m else None


def survivors_at(conn, at: float) -> list[dict]:
    """Proposals whose newest verdict before `at` is a passed screen, newest first, as the measure step read them then."""
    rows = conn.execute(
        "SELECT p.name, p.lane, p.attaches_to, v.detail FROM proposals p JOIN verdicts v ON v.id = "
        "(SELECT MAX(w.id) FROM verdicts w WHERE w.proposal_id = p.id AND w.decided_at < ?) "
        "WHERE v.tier = ? AND v.outcome = 'screened' ORDER BY v.id DESC", (at, ms.SCREEN)).fetchall()
    return [dict(r) for r in rows]


def held_at(conn, at: float) -> list[dict]:
    """Pauses begun before `at` and not yet decided then, oldest first: the step resumes these before anything new."""
    from harness import adopt
    out, seen = [], set()
    for r in conn.execute("SELECT proposal, challenger, lane, out, state FROM paused_runs ORDER BY id DESC"):
        name = r["proposal"] or r["challenger"]
        began = started_at(r["out"])
        if name in seen or began is None or began >= at:
            continue
        seen.add(name)
        decided = conn.execute(
            "SELECT 1 FROM verdicts v JOIN proposals p ON p.id = v.proposal_id WHERE p.name = ? AND v.tier = ? "
            "AND v.decided_at >= ? AND v.decided_at < ? LIMIT 1", (name, adopt.TIER, began, at)).fetchone()
        if r["state"] != "stale" and decided is None:
            out.append({"name": name, "lane": r["lane"]})
    return out[::-1]


def measured(conn, since: float, until: float) -> list[dict]:
    """What the measure step worked on between `since` and `until`, in order: fresh starts by out dir, resumes by pause or verdict."""
    got: dict = {}
    for name, lane, path, at, how in conn.execute(
            "SELECT proposal, lane, out, paused_at, 'paused' FROM paused_runs UNION ALL "
            "SELECT p.name, u.lane, u.path, v.decided_at, 'decided' FROM verdicts v "
            "JOIN proposals p ON p.id = v.proposal_id JOIN runs u ON u.id = v.run_id WHERE v.tier = 'adopt'"):
        began = started_at(path)
        if began is not None and since <= began < until:
            at, how = began, "fresh"
        elif at is None or not since <= float(at) < until:
            continue
        else:
            # A resumed slice ran up to one budget before it paused or was decided.
            at = max(since, float(at) - power.BUDGET_MIN * 60)
        if name not in got or at < got[name]["at"]:
            got[name] = {"at": at, "name": name, "lane": lane, "how": how}
    return sorted(got.values(), key=lambda r: r["at"])


def queue(conn, rows: list[dict], held: list[dict], want: str = "", now: float | None = None,
          gate: bool | None = None) -> list[dict]:
    """The measure step's later stages on `rows` as given: families, the slot (memory unchecked), pauses, repo rows."""
    from harness import family, repo_gate
    st = family.standing(conn)
    ordered, _, _ = family.reserve(family.measure_order(rows, st), st, now=now, fits=lambda r: (True, ""))
    names = {r["name"] for r in held}
    return repo_gate.order(held + [r for r in ordered if r.get("name") not in names], conn, want, on=gate)


def walk(rows: list[dict], window_s: float, price) -> tuple[list[dict], list[dict]]:
    """(taken, cut): each row takes min(its minutes, one slice) of what is left, an unpriced row a slice; none past 0."""
    slice_s, left, taken, cut = power.BUDGET_MIN * 60, window_s, [], []
    for r in rows:
        if left <= 0:
            cut.append(r)
            continue
        mins = price(r)
        spend = min(slice_s, mins * 60 if mins else slice_s, left)
        left -= spend
        taken.append({**r, "spend_s": spend})
    return taken, cut


def nights(now: float, days: int, hour: int) -> list[float]:
    """Sweep starts at `hour` local on each of the last `days` evenings, oldest first, all before `now`."""
    today = datetime.fromtimestamp(now).replace(hour=hour, minute=0, second=0, microsecond=0)
    starts = [(today - timedelta(days=d)).timestamp() for d in range(days + 1)]
    return sorted(s for s in starts if s + power.SWEEP_CEILING_H * 3600 <= now)[-days:]


def replay(conn, days: int, *, now: float | None = None, want: str = "", hour: int | None = None) -> list[dict]:
    """Per night: the queue it faced, both orders walked against its measure window, and what it measured; a night that
    measured in the repo lane replays with the repo gate on."""
    from harness import ceiling, heartbeat
    from harness.commands import measure as measure_cmd
    now = time.time() if now is None else now
    hour = heartbeat.discover_hours()[0] if hour is None else hour
    out = []
    for start in nights(now, days, hour):
        end = start + power.SWEEP_CEILING_H * 3600
        began = measured(conn, start, end + 3600)
        at = began[0]["at"] if began else start + power.SWEEP_CEILING_H * 3600 * ceiling.SCREEN_FRACTION
        gate = any(b["lane"] == "repo" for b in began) or None
        rows = [r for r in survivors_at(conn, at) if measure_cmd.takes(r, want)]
        ctx = measure_gain.context(conn, before=at)
        by_gain, gains = measure_gain.order(conn, rows, want, ctx=ctx)
        held = [r for r in held_at(conn, at) if measure_cmd.takes(r, want)]

        def price(r, ctx=ctx):
            return measure_gain.score(ctx, r, want).minutes
        orders = {}
        for label, got in (("survivors", rows), ("gain", by_gain)):
            taken, cut = walk(queue(conn, got, held, want, now=at, gate=gate), max(0.0, end - at), price)
            orders[label] = {"taken": taken, "cut": cut}
        out.append({"start": start, "measure_at": at, "window_s": max(0.0, end - at), "queued": len(rows),
                    "held": [r["name"] for r in held], "began": began, "gains": gains, **orders})
    return out


def _names(rows, n=None) -> str:
    got = [f"{r['name']} ({r.get('lane', '')}{', %dm' % round(r['spend_s'] / 60) if 'spend_s' in r else ''})"
           for r in rows[:n]]
    return "; ".join(got) or "-"


def report(conn, days: int, *, now: float | None = None, want: str = "", head: int = 5) -> list[str]:
    """Lines for `soh measure-order --replay`: per night, what each order starts and what the ceiling cuts."""
    lines = [f"replay of {days} night(s): survivors as of each night's first measurement, ordered newest screen "
             f"first (as run) and by gain per GPU-minute (as of that night's evidence), each walked against the "
             f"window to the {power.SWEEP_CEILING_H:g} h ceiling at up to {power.BUDGET_MIN:g} min a measurement; "
             f"cost from today's stored seconds per call"]
    for n in replay(conn, days, now=now, want=want):
        when = time.strftime("%Y-%m-%d", time.localtime(n["start"]))
        lines.append(f"\n{when}: measure from {time.strftime('%H:%M', time.localtime(n['measure_at']))}, "
                     f"{n['window_s'] / 60:.0f} min to the ceiling; {n['queued']} survivor(s), "
                     f"{len(n['held'])} paused")
        lines.append(f"  measured:       {_names(n['began'])}")
        for label in ("survivors", "gain"):
            o = n[label]
            lines.append(f"  {label + ' order:':<15} {_names(o['taken'], head)}")
            lines.append(f"  {'cut:':<15} {len(o['cut'])}: {_names(o['cut'], head)}")
    return lines


def today(conn, want: str = "", head: int = 0) -> list[str]:
    """Lines for `soh measure-order`: today's survivors by gain per GPU-minute, each key and its evidence."""
    from harness.commands import measure as measure_cmd
    rows = [r for r in survivors_at(conn, time.time()) if measure_cmd.takes(r, want)]
    _, gains = measure_gain.order(conn, rows, want)
    return [f"{i + 1:>3}. {g.line()}" for i, g in enumerate(gains[:head or None])]
