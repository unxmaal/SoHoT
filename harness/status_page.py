"""The LAN status page: /status and /status.json from the morning, deploy and queue gatherers (#2075)."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

#: Seconds a gathered status is served before a request gathers again; the page reloads at this pace. #2075.
REFRESH_S = 60.0
#: Days of monit alerts the page looks back through for the last one sent.
ALERT_DAYS = 7
#: Seconds the status page's timeline strip reaches back. #2078.
TIMELINE_S = 86400.0
#: Seconds with no screen or measure run, while candidates wait, before the page goes red. #2083.
SPEND_STALE_S = 2 * 86400.0
DEPLOYED = "deployed"
_SECRET_NAME = re.compile(r"(WEBHOOK|TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|_KEY$|^KEY$|DSN|CREDENTIAL)", re.I)
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>)\]]+", re.I)
_USERINFO = re.compile(r"//[^/@\s:]+:[^/@\s]+@")
_ASSIGN = re.compile(r"\b(\w*(?:WEBHOOK|TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|DSN)\w*)(\s*[=:]\s*)(\S+)", re.I)
_LOCAL_HOST = re.compile(r"^(localhost|127\.\d+\.\d+\.\d+|\[::1\]|[\w-]+\.local|10\.[\d.]+|192\.168\.[\d.]+)(:\d+)?$", re.I)
_MONIT_OK = re.compile(r"^(ok|running|accessible|online.*|status ok|initializing|waiting|not monitored)$", re.I)

_lock = threading.Lock()
_cache: dict = {}


def _secret_values(environ=None, home: Path | None = None) -> list[str]:
    from harness import monitor
    env = dict(os.environ if environ is None else environ)
    env.update(monitor.read_env(monitor.env_path(home)))
    return sorted({v for k, v in env.items() if _SECRET_NAME.search(k) and isinstance(v, str) and len(v) >= 6},
                  key=len, reverse=True)


def _url(m: re.Match) -> str:
    url = _USERINFO.sub("//", m.group(0))
    host = url.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0]
    return url if _LOCAL_HOST.match(host) else f"{url.split('://', 1)[0]}://<redacted>"


def scrub(obj, secrets: list[str]):
    """`obj` with every secret value, credential assignment and non-LAN URL replaced by <redacted>."""
    if isinstance(obj, dict):
        return {k: scrub(v, secrets) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, secrets) for v in obj]
    if not isinstance(obj, str):
        return obj
    obj = _ASSIGN.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", _URL.sub(_url, obj))
    for s in secrets:
        obj = obj.replace(s, "<redacted>")
    return obj


def _section(fn, *args) -> dict:
    """fn(*args) stamped with when it was read; an exception is the section's error, not the page's."""
    try:
        got = fn(*args)
    except Exception as exc:  # noqa: BLE001 - one section failing must not take the page down
        got = {"error": f"{type(exc).__name__}: {exc}"[:400]}
    return {**got, "as_of": time.time()}


def store(conn, why: str = "", home: Path | None = None) -> dict:
    from harness import deploy, store_service
    out = {"up": conn is not None, "why": why, "schema": None, "backup_at": None}
    if conn is not None:
        out["schema"] = deploy._store_schema(conn)
    dumps = store_service.backups(home)
    if dumps:
        out["backup_at"] = dumps[-1].stat().st_mtime
    return out


WAITING_SHOWN = 20


def _waiting(conn, jobs: list[dict], now: float) -> list[dict]:
    """The first WAITING_SHOWN pending jobs in run order, each with whether the benchmarks hold keeps it back. #2135."""
    from harness import hold
    from harness import workqueue as wq
    held = hold.active(conn, now)
    return [{"id": wq.label(j["id"]), "kind": j.get("kind"), "title": j.get("title"), "priority": int(j.get("priority") or 0),
             "held": hold.held_back(conn, j, held)} for j in jobs[:WAITING_SHOWN]]


def queue(conn, now: float) -> dict:
    from harness import queue_hold, queue_pause, queue_stale
    from harness import workqueue as wq
    body = queue_pause.body()
    out = {"paused": body is not None, "paused_since": None, "reason": "", "by": None,
           "running": [], "pending": None, "last_moved": None}
    if body is not None:
        out["paused_since"], out["reason"], out["by"] = queue_hold.since(body), queue_hold.reason(body), queue_hold.by_of(body)
        out["who"] = queue_hold.who(body)
        out["deploy_hold"] = queue_hold.deploy_hold(body)
    if conn is None:
        out["why"] = "store down: running and pending jobs not read"
        return out
    out["running"] = [{k: j.get(k) for k in ("id", "kind", "title", "started_at")}
                      for j in wq._select(conn, "WHERE state = ?", (wq.RUNNING,))]
    waiting = wq.pending(conn)
    out["pending"] = len(waiting)
    out["waiting"] = _waiting(conn, waiting, now)
    out["last_moved"] = queue_stale.last_moved(conn)
    return out


def deploy_section(conn, now: float, where: Path | None, git=None) -> dict:
    from harness import deploy, morning, paths
    tree = morning.deploy(paths.deploy_checkout() if where is None else where, git=git)
    out = {"head": tree.get("head", ""), "main": tree.get("main", ""), "behind": tree.get("behind"),
           "tree_why": tree.get("why", ""), "last": None, "failing": 0, "wait": None, "blocked": ""}
    if conn is None:
        out["why"] = "store down: deploy history not read"
        return out
    got = deploy.status(conn)
    out["head"] = got["head"] or out["head"]
    out["blocked"] = got["blocked"]
    done = [d for d in got["recent"] if d.get("outcome")]
    if got["recent"]:
        d = got["recent"][0]
        out["last"] = {"id": d["id"], "sha": d["sha"], "outcome": d.get("outcome") or "", "at": d.get("started_at"),
                       "detail": d.get("detail") or "", "line": deploy.line(d)}
    for d in done:
        if d["outcome"] == DEPLOYED:
            break
        out["failing"] += 1
    out["wait"] = morning.deploy_wait(conn, now)
    if out["wait"]:
        out["wait"]["line"] = deploy.wait_line(out["wait"])
    return out


def next_run(hours: list[int], now: float) -> float | None:
    """The next local time on the hour among `hours`, after `now`."""
    if not hours:
        return None
    base = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0)
    for days in (0, 1):
        for h in sorted(hours):
            t = (base.replace(hour=h) + timedelta(days=days)).timestamp()
            if t > now:
                return t
    return None


def discovery_failed(disc: dict) -> bool:
    return disc.get("status") == "finished" and bool(disc.get("failure") or disc.get("rc") not in (0, None))


def discovery(now: float, beat=None) -> dict:
    from harness import heartbeat
    beat = heartbeat.summary() if beat is None else beat
    out = {"status": "", "started": None, "finished": None, "rc": None, "failure": "", "line": "", "age_s": None,
           "next": next_run(heartbeat.discover_hours(), now), "overdue": heartbeat.overdue(beat) if beat else ""}
    if beat:
        out.update({k: beat.get(k) for k in ("status", "started", "finished", "rc", "line", "age_s")})
        out["failure"] = beat.get("error") or ""
    else:
        out["overdue"] = heartbeat.overdue(None)
    return out


def spend(conn, now: float) -> dict:
    """When the last screen or measure run ran, and how many candidates wait for a screen. #2083."""
    from harness import machine_scope
    from harness import memory_store as ms
    if conn is None:
        return {"error": "store down: screens and measures not read"}
    here, mine = machine_scope.here(conn, "runs.ran_here")
    got = conn.execute(f"SELECT MAX(COALESCE(generated_at, recorded_at)) AS t FROM runs WHERE {here}", mine).fetchone()
    last = got[0] if got else None
    return {"last_run_at": last, "waiting": ms.judgeable_total(conn)}


def queued_sweep(conn) -> dict:
    """The sweep steps waiting in the queue: what turning continuous discovery off cancels. #2116."""
    from harness.commands import loop_steps
    return {"jobs": loop_steps.waiting(conn)} if conn is not None else {"jobs": [], "why": "store down: queue not read"}


def spend_stalled(sp: dict, now: float) -> bool:
    """Candidates wait and nothing was screened or measured for SPEND_STALE_S. #2083."""
    if sp.get("error") or not sp.get("waiting"):
        return False
    last = sp.get("last_run_at")
    return last is None or now - float(last) > SPEND_STALE_S


def monitor_section(now: float, status=None, home: Path | None = None) -> dict:
    from harness import monitor
    got = (status or monitor.status)()
    rows = []
    for ln in got.get("summary") or []:
        parts = re.split(r"\s{2,}", ln.strip())
        if len(parts) >= 3 and parts[0] != "Service Name" and not ln.lstrip().startswith("Monit"):
            rows.append({"check": parts[0], "state": parts[1], "type": parts[2], "ok": bool(_MONIT_OK.match(parts[1]))})
    sent = monitor.alerts(now - ALERT_DAYS * 86400, home)
    return {"installed": got.get("installed"), "running": got.get("running"), "current": got.get("current"),
            "alerting": bool(got.get("webhook")), "problems": got.get("problems") or [], "checks": rows,
            "last_alert": monitor.line(sent[-1]) if sent else "", "last_alert_at": (sent[-1].get("at") if sent else None)}


def services(now: float, health=None, reach=None) -> dict:
    from harness import morning, node_reach
    lane = (health or morning.lane_health)(morning.MODEL_LANE)
    nodes = (reach or node_reach.summary)(now - 86400, now)
    return {"lane": lane, "nodes": [{"node": n["node"], "down_now": n["down_now"], "down_s": n["down_s"]} for n in nodes]}


def ratio(conn, now: float, flow=None) -> dict:
    from harness import ledger, morning, token_flow
    out = {"line": "", "terms": "", "headline": None, "days": [], "causes": [], "counted": None}
    if conn is not None:
        out["headline"] = morning.ratio(conn, now)
        out["line"] = ledger.ratio_line(out["headline"]) if out["headline"] else "no ledger_days table"
        if out["headline"]:
            out["days"] = ratio_days(conn, out["headline"]["week"])
    else:
        out["line"] = "store down: ratio not read"
    m = (flow or token_flow.morning)(now)
    out["terms"] = token_flow.terms_line(m)
    out["causes"], out["counted"] = causes(m)
    return out


def ratio_days(conn, week: dict) -> list[dict]:
    """Local and cloud tokens for each day of the ratio's week, None where the day has no count. #2078."""
    from harness import ledger
    got = {r["day"]: r.get("ratio") or {} for r in ledger.recorded(conn, week["first_day"])}
    first = date.fromisoformat(week["first_day"])
    want = [(first + timedelta(days=i)).isoformat() for i in range(week["of"])]
    return [{"day": d, "local": got.get(d, {}).get("local"), "cloud": got.get(d, {}).get("cloud")} for d in want]


def causes(m: dict | None) -> tuple[list[dict], int | None]:
    """The morning account's largest terms and the rest as other, against counted cloud. #2078."""
    if not m or not m.get("available") or not m.get("counted"):
        return [], None
    got = [{"term": t["term"], "tokens": t["tokens"]} for t in m["terms"] if t.get("tokens")]
    rest = m["counted"] - sum(t["tokens"] for t in got)
    return got + ([{"term": "other", "tokens": rest}] if rest > 0 else []), m["counted"]


def timeline(conn, now: float, disc: dict, q: dict, home: Path | None = None) -> dict:
    """Deploys, discovery runs, finished jobs, monit alerts and the pause over the last TIMELINE_S. #2078."""
    from harness import deploy, monitor
    from harness import workqueue as wq
    since = now - TIMELINE_S
    ev = []
    if disc.get("started"):
        bad = disc.get("status") == "stalled" or discovery_failed(disc)
        ev.append({"kind": "discovery", "at": disc["started"], "end": disc.get("finished") or now,
                   "state": "bad" if bad else "ok", "label": f"discovery {disc.get('status') or 'run'}"})
    if q.get("paused") and q.get("paused_since"):
        ev.append({"kind": "pause", "at": q["paused_since"], "end": now, "state": "warn", "label": "queue paused"})
    ev += [{"kind": "alert", "at": a.get("at"), "state": "warn" if a.get("held") else "bad",
            "label": f"{a.get('kind')} {a.get('service')}: {str(a.get('description') or '')[:80]}"}
           for a in monitor.alerts(since, home) if a.get("at")]
    if conn is not None:
        for d in deploy.since(conn, since):
            out = d.get("outcome") or ""
            ev.append({"kind": "deploy", "at": d["started_at"], "state": "ok" if out == DEPLOYED else "bad" if out else "unknown",
                       "label": f"deploy {d['id']} {(d.get('sha') or '')[:8]} {out or 'running'}"})
        here, args = wq._claimed(conn)
        rows = conn.execute("SELECT id, kind, state, finished_at FROM jobs WHERE finished_at >= ? AND state IN (?, ?) "
                            f"AND {here} ORDER BY finished_at", (since, wq.DONE, wq.FAILED, *args)).fetchall()
        ev += [{"kind": "job", "at": j["finished_at"], "state": "ok" if j["state"] == wq.DONE else "bad",
                "label": f"job {wq.label(j['id'])} {j['kind']} {j['state']}"} for j in rows]
    ev = [e for e in ev if float(e.get("end") or e["at"]) >= since]
    return {"since": since, "until": now, "events": sorted(ev, key=lambda e: float(e["at"]))}


def banner(r: dict, now: float) -> list[str]:
    """What needs the owner, one line each: the Needs-you band's conditions."""
    from harness import needs_you
    return [c["line"] for c in needs_you.conditions(r)]


def _features(conn, now: float, q: dict) -> dict:
    from harness import features
    return features.gather(conn, now, q)


def gather(now: float | None = None, *, connect=None, beat=None, where=None, git=None, mon=None, health=None,
           reach=None, flow=None, home: Path | None = None, environ=None, features=None, light: bool = False) -> dict:
    """Every section, each with its own as_of; with the store down the store-free sections still read. `light` skips the
    ratio and the 24 h strip, which the Needs-you alert pass does not need."""
    from harness import morning, needs_you
    now = time.time() if now is None else now
    conn, why = None, ""
    try:
        conn = (connect or morning.snapshot)()
    except Exception as exc:  # noqa: BLE001 - a down store is the page's news, not its failure
        why = f"{type(exc).__name__}: {exc}"[:400]
    try:
        r = {"generated": now, "refresh_s": REFRESH_S,
             "store": _section(store, conn, why, home),
             "queue": _section(queue, conn, now),
             "deploy": _section(deploy_section, conn, now, where, git),
             "discovery": {**_section(discovery, now, beat), "spend": _section(spend, conn, now),
                           "queued": _section(queued_sweep, conn)},
             "monitor": _section(monitor_section, now, mon, home),
             "services": _section(services, now, health, reach),
             "ratio": {} if light else _section(ratio, conn, now, flow)}
        r["timeline"] = {} if light else _section(timeline, conn, now, r["discovery"], r["queue"], home)
        r["features"] = _section(features or _features, conn, now, r["queue"])
        r["stops"] = {"holds": _section(needs_you.read_holds, conn, now), "jobs": _section(needs_you.read_jobs, conn, now),
                      "gateway": _section(needs_you.read_gateway), "gate": _section(needs_you.read_gate),
                      "monit": _section(needs_you.read_monit, now, home, r["monitor"])}
        if (r["queue"].get("deploy_hold") or {}).get("live"):
            r["deploy"]["in_progress"] = r["queue"]["deploy_hold"]
    finally:
        if conn is not None:
            conn.close()
    r["needs_you"] = needs_you.conditions(r)
    r["banner"] = [c["line"] for c in r["needs_you"]]
    return scrub(r, _secret_values(environ, home))


def cached(now: float | None = None, gather_=None) -> dict:
    """The last gather while it is younger than REFRESH_S, else a new one; one gather at a time."""
    now = time.time() if now is None else now
    with _lock:
        got = _cache.get("r")
        if got is None or now - got["generated"] >= REFRESH_S:
            got = _cache["r"] = (gather_ or gather)(now)
        return got


def forget() -> None:
    """Drop the cached gather: the next read shows what an owner action just changed. #2116."""
    with _lock:
        _cache.clear()


def as_json(r: dict) -> str:
    return json.dumps(r, indent=1, sort_keys=True, default=str)


def _t(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(t))) if t else "never"


def _ago(t, now: float) -> str:
    if not t:
        return "never"
    s = max(0.0, now - float(t))
    return f"{_t(t)} ({s / 3600:.1f} h ago)" if s >= 3600 else f"{_t(t)} ({s / 60:.0f} min ago)"


def _spend_line(sp: dict, now: float) -> str:
    if sp.get("error"):
        return f"screens and measures not read: {sp['error']}"
    return f"last screen or measure {_ago(sp.get('last_run_at'), now)}; {sp.get('waiting')} candidate(s) waiting"


def lines(r: dict) -> dict[str, list[str]]:
    """Each section as plain lines, the page's text."""
    now = r["generated"]
    s, q, d, disc, mon, sv, ra = (r[k] for k in ("store", "queue", "deploy", "discovery", "monitor", "services", "ratio"))
    out = {}
    out["Deploy"] = d.get("error") and [d["error"]] or [
        f"serving {(d.get('head') or 'unknown')[:8]}; origin/main {(d.get('main') or 'unknown')[:8]}"
        + (f", {d['behind']} behind" if d.get("behind") else "") + (f" ({d['tree_why']})" if d.get("tree_why") else ""),
        f"last: {d['last']['line']}" if d.get("last") else (d.get("why") or "no deploy in 7 days"),
        f"waiting: {d['wait']['line']}" if d.get("wait") else f"next: {d.get('blocked') or 'a deploy may start at the next poll'}"]
    out["Queue"] = q.get("error") and [q["error"]] or [
        (f"PAUSED since {_ago(q['paused_since'], now)}: {q['reason']}" + (f" by {q['by']}" if q.get("by") else ""))
        if q.get("paused") else "running (not paused)",
        *[f"running job {j['id']} {j['kind']}: {j['title']} since {_t(j['started_at'])}" for j in q.get("running") or []],
        q.get("why") or f"{q.get('pending')} pending; last moved {_ago(q.get('last_moved'), now)}"]
    out["Discovery"] = disc.get("error") and [disc["error"]] or [
        disc.get("line") or "no discovery loop heartbeat",
        f"started {_t(disc.get('started'))}, finished {_t(disc.get('finished'))}, rc {disc.get('rc')}"
        + (f", error: {disc['failure']}" if disc.get("failure") else ""),
        f"next scheduled {_t(disc.get('next'))}" + (f"; overdue: {disc['overdue']}" if disc.get("overdue") else ""),
        _spend_line(disc.get("spend") or {}, now)]
    out["Monitor"] = mon.get("error") and [mon["error"]] or [
        f"monit {'running' if mon.get('running') else 'NOT running'}, config {'current' if mon.get('current') else 'not current'}, "
        f"alerts {'to the webhook' if mon.get('alerting') else 'desktop only'}",
        *[f"{c['check']}: {c['state']}" for c in mon.get("checks") or []],
        *mon.get("problems", []),
        f"last alert: {mon.get('last_alert') or 'none in ' + str(ALERT_DAYS) + ' days'}"]
    lane = sv.get("lane") or {}
    gen = {True: "generating", False: "NOT generating", None: "unknown"}[lane.get("generating")] if lane else "unknown"
    out["Services"] = sv.get("error") and [sv["error"]] or [
        f"{lane.get('lane')} lane {lane.get('spec') or ''} at {lane.get('base') or '?'}: {gen}"
        + (f" ({lane['why']})" if lane.get("why") else ""),
        *[f"node {n['node']}: {'DOWN' if n['down_now'] else 'up'}, out {n['down_s'] / 60:.0f} min in 24 h"
          for n in sv.get("nodes") or []]]
    out["Ratio"] = ra.get("error") and [ra["error"]] or [ra.get("line") or "", ra.get("terms") or ""]
    out["Store"] = [f"store {'up' if s.get('up') else 'DOWN'}"
                    + (f" at schema {s['schema']}" if s.get("schema") else "") + (f": {s['why']}" if s.get("why") else ""),
                    s.get("error") or f"last backup {_ago(s.get('backup_at'), now)}"]
    return {k: [x for x in v if x] for k, v in out.items()}


def page(r: dict, now: float | None = None, extra: str = "", token: str = "") -> str:
    from harness import status_view
    return status_view.page(r, lines(r), now, extra, token)
