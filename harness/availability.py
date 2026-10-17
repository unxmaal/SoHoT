"""Incidents and uptime per text lane, derived from the runs of lane_probes rows, never written (#924)."""
from __future__ import annotations

from datetime import datetime

from harness.lane_probe import DOWN, SKIPPED, SLOW, UP

#: The weekly share of judged probes each adopted text lane should answer.
TARGET = 0.99


def rows(conn, lane: str, machine_id, since: float, until: float) -> list[dict]:
    """The lane's rows from the last up before `since` (or its first row) to `until`, oldest first."""
    mine = "(machine_id = ? OR (machine_id IS NULL AND ? IS NULL))"
    got = conn.execute(f"SELECT MAX(at) AS at FROM lane_probes WHERE lane = ? AND {mine} AND outcome = ? AND at < ?",
                       (lane, machine_id, machine_id, UP, since)).fetchone()
    start = got["at"] if got and got["at"] is not None else float("-inf")
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM lane_probes WHERE lane = ? AND {mine} AND at >= ? AND at <= ? ORDER BY at, id",
        (lane, machine_id, machine_id, start, until))]


def incidents(probes: list[dict]) -> list[dict]:
    """Each maximal run of down rows in one lane's probes; slow and skipped rows neither open nor close one."""
    out, cur, last_up = [], None, None
    for r in probes:
        if r["outcome"] == DOWN:
            if cur is None:
                cur = {"lane": r["lane"], "spec": r.get("spec", ""), "base": r.get("base", ""),
                       "after": last_up, "first_down": r["at"], "last_down": r["at"], "up_at": None,
                       "downs": 0, "error": r.get("error") or r.get("reason") or ""}
            cur["last_down"] = r["at"]
            cur["downs"] += 1
        elif r["outcome"] == UP:
            if cur is not None:
                cur["up_at"] = r["at"]
                out.append(cur)
                cur = None
            last_up = r["at"]
    if cur is not None:
        out.append(cur)
    for i in out:
        i["open"] = i["up_at"] is None
        i["at_least_s"] = i["last_down"] - i["first_down"]
        i["at_most_s"] = None if i["open"] or i["after"] is None else i["up_at"] - i["after"]
    return out


def uptime(probes: list[dict], since: float) -> dict:
    """up / (up + down + slow) over the rows at or after `since`; skipped rows are counted apart."""
    n = {o: 0 for o in (UP, DOWN, SLOW, SKIPPED)}
    for r in probes:
        if r["at"] >= since and r["outcome"] in n:
            n[r["outcome"]] += 1
    judged = n[UP] + n[DOWN] + n[SLOW]
    return {**n, "judged": judged, "rate": n[UP] / judged if judged else None}


def lanes_seen(conn, machine_id, since: float) -> list[str]:
    return [r["lane"] for r in conn.execute(
        "SELECT DISTINCT lane FROM lane_probes WHERE at >= ? AND (machine_id = ? OR (machine_id IS NULL AND ? IS NULL)) "
        "ORDER BY lane", (since, machine_id, machine_id))]


def report(conn, since: float, now: float, machine_id=None, lanes=None) -> dict:
    """Per lane: uptime since `since` and every incident that was open at or after it."""
    out = {"since": since, "until": now, "target": TARGET, "lanes": {}, "incidents": []}
    for lane in lanes or lanes_seen(conn, machine_id, since):
        got = rows(conn, lane, machine_id, since, now)
        seen = [i for i in incidents(got) if i["open"] or i["up_at"] >= since]
        out["lanes"][lane] = {**uptime(got, since), "incidents": len(seen),
                              "open": any(i["open"] for i in seen)}
        out["incidents"].extend(seen)
    out["incidents"].sort(key=lambda i: i["first_down"])
    return out


def has_table(conn) -> bool:
    try:
        conn.execute("SELECT 1 FROM lane_probes LIMIT 1").fetchall()
    except Exception:  # noqa: BLE001
        return False
    return True


def here(conn):
    from harness import runs
    got = runs.here(conn)
    return got[0] if got else None


def hm(t) -> str:
    return datetime.fromtimestamp(float(t)).strftime("%m-%d %H:%M") if t is not None else "--"


def span(s) -> str:
    if s is None:
        return "?"
    s = int(round(s))
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def incident_line(i: dict) -> str:
    """One incident: lane, both bounds of its start and end, how long, open or closed, its error."""
    start = f"down after {hm(i['after'])}, by {hm(i['first_down'])}" if i["after"] is not None else \
        f"down by {hm(i['first_down'])} (no up before it)"
    if i["open"]:
        end = f"still down at {hm(i['last_down'])} (open, {span(i['at_least_s'])} at least)"
    else:
        most = f" to {span(i['at_most_s'])}" if i["at_most_s"] is not None else ""
        end = f"up again after {hm(i['last_down'])}, by {hm(i['up_at'])} ({span(i['at_least_s'])}{most})"
    return f"{i['lane']}: {start}; {end}: {(i['error'] or '-')[:160]}"
