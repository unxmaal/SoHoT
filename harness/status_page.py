"""The LAN status page: /status and /status.json from the morning, deploy and queue gatherers (#2075)."""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

#: Seconds a gathered status is served before a request gathers again; the page reloads at this pace. #2075.
REFRESH_S = 60.0
#: Days of monit alerts the page looks back through for the last one sent.
ALERT_DAYS = 7
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


def queue(conn, now: float) -> dict:
    from harness import queue_hold, queue_pause, queue_stale
    from harness import workqueue as wq
    body = queue_pause.body()
    out = {"paused": body is not None, "paused_since": None, "reason": "", "by": None,
           "running": [], "pending": None, "last_moved": None}
    if body is not None:
        out["paused_since"], out["reason"], out["by"] = queue_hold.since(body), queue_hold.reason(body), queue_hold.by_of(body)
    if conn is None:
        out["why"] = "store down: running and pending jobs not read"
        return out
    out["running"] = [{k: j.get(k) for k in ("id", "kind", "title", "started_at")}
                      for j in wq._select(conn, "WHERE state = ?", (wq.RUNNING,))]
    out["pending"] = len(wq.pending(conn))
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


def discovery(now: float, beat=None) -> dict:
    from harness import heartbeat
    beat = heartbeat.summary() if beat is None else beat
    out = {"status": "", "started": None, "finished": None, "rc": None, "failure": "", "line": "",
           "next": next_run(heartbeat.discover_hours(), now), "overdue": heartbeat.overdue(beat) if beat else ""}
    if beat:
        out.update({k: beat.get(k) for k in ("status", "started", "finished", "rc", "line")})
        out["failure"] = beat.get("error") or ""
    else:
        out["overdue"] = heartbeat.overdue(None)
    return out


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
    out = {"line": "", "terms": "", "headline": None}
    if conn is not None:
        out["headline"] = morning.ratio(conn, now)
        out["line"] = ledger.ratio_line(out["headline"]) if out["headline"] else "no ledger_days table"
    else:
        out["line"] = "store down: ratio not read"
    out["terms"] = token_flow.terms_line((flow or token_flow.morning)(now))
    return out


def banner(r: dict, now: float) -> list[str]:
    """What needs the owner, one line each."""
    from harness import queue_stale
    out = []
    s, q, d, disc, mon = r["store"], r["queue"], r["deploy"], r["discovery"], r["monitor"]
    if not s.get("up"):
        out.append(f"store down: {s.get('why') or s.get('error') or 'unreachable'}")
    if d.get("failing"):
        last = d.get("last") or {}
        out.append(f"deploy failing: {d['failing']} in a row, last {last.get('line') or last.get('outcome')}")
    if q.get("paused") and q.get("paused_since") and now - q["paused_since"] > queue_stale.QUEUE_STALE_S:
        out.append(f"queue paused {(now - q['paused_since']) / 3600:.1f} h: {q.get('reason')}")
    if disc.get("status") == "stalled":
        out.append(f"discovery stalled: {disc.get('line')}")
    elif disc.get("status") == "finished" and (disc.get("failure") or disc.get("rc") not in (0, None)):
        out.append(f"discovery failed: {disc.get('failure') or 'rc ' + str(disc.get('rc'))}")
    if disc.get("overdue"):
        out.append(f"discovery overdue: {disc['overdue']}")
    if mon.get("error"):
        out.append(f"monitor not read: {mon['error']}")
    elif not mon.get("running"):
        out.append("monit is not running: " + "; ".join(mon.get("problems") or ["no checks run"]))
    out += [f"check {c['check']} is {c['state']}" for c in mon.get("checks") or [] if not c["ok"]]
    out += [f"node {n['node']} is down" for n in (r["services"].get("nodes") or []) if n["down_now"]]
    lane = r["services"].get("lane") or {}
    if lane.get("generating") is False:
        out.append(f"the {lane.get('lane')} lane cannot generate: {lane.get('why') or lane.get('base')}")
    out += [f"{k} not read: {r[k]['error']}" for k in ("store", "queue", "deploy", "discovery", "services", "ratio")
            if r[k].get("error")]
    return out


def gather(now: float | None = None, *, connect=None, beat=None, where=None, git=None, mon=None, health=None,
           reach=None, flow=None, home: Path | None = None, environ=None) -> dict:
    """Every section, each with its own as_of; with the store down the store-free sections still read."""
    from harness import morning
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
             "discovery": _section(discovery, now, beat),
             "monitor": _section(monitor_section, now, mon, home),
             "services": _section(services, now, health, reach),
             "ratio": _section(ratio, conn, now, flow)}
    finally:
        if conn is not None:
            conn.close()
    r["banner"] = banner(r, now)
    return scrub(r, _secret_values(environ, home))


def cached(now: float | None = None, gather_=None) -> dict:
    """The last gather while it is younger than REFRESH_S, else a new one; one gather at a time."""
    now = time.time() if now is None else now
    with _lock:
        got = _cache.get("r")
        if got is None or now - got["generated"] >= REFRESH_S:
            got = _cache["r"] = (gather_ or gather)(now)
        return got


def as_json(r: dict) -> str:
    return json.dumps(r, indent=1, sort_keys=True, default=str)


def _t(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(t))) if t else "never"


def _ago(t, now: float) -> str:
    if not t:
        return "never"
    s = now - float(t)
    return f"{_t(t)} ({s / 3600:.1f} h ago)" if s >= 3600 else f"{_t(t)} ({s / 60:.0f} min ago)"


def lines(r: dict) -> dict[str, list[str]]:
    """Each section as plain lines, the page's text."""
    now = r["generated"]
    s, q, d, disc, mon, sv, ra = (r[k] for k in ("store", "queue", "deploy", "discovery", "monitor", "services", "ratio"))
    out = {}
    out["Deploy"] = d.get("error") and [d["error"]] or [
        f"serving {(d.get('head') or 'unknown')[:12]}; origin/main {(d.get('main') or 'unknown')[:12]}"
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
        f"next scheduled {_t(disc.get('next'))}" + (f"; overdue: {disc['overdue']}" if disc.get("overdue") else "")]
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


_KEYS = {"Deploy": "deploy", "Queue": "queue", "Discovery": "discovery", "Monitor": "monitor",
         "Services": "services", "Ratio": "ratio", "Store": "store"}
_CSS = """:root{--bg:#fff;--fg:#1b1b1b;--dim:#666;--bad:#b00020;--badbg:#fde7ea;--line:#ddd}
@media (prefers-color-scheme: dark){:root{--bg:#141414;--fg:#e8e8e8;--dim:#999;--bad:#ff8a80;--badbg:#3a1416;--line:#333}}
body{background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px}
h1{font-size:20px}h2{font-size:16px;margin:18px 0 4px;border-bottom:1px solid var(--line)}
.asof{color:var(--dim);font-weight:normal;font-size:12px}
.banner{background:var(--badbg);color:var(--bad);border:2px solid var(--bad);padding:8px 12px;border-radius:6px}
.ok{color:var(--dim)}ul{margin:4px 0;padding-left:20px}li{overflow-wrap:anywhere}"""


def page(r: dict) -> str:
    e = html.escape
    out = ["<!doctype html><html><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<meta http-equiv='refresh' content='{int(r.get('refresh_s') or REFRESH_S)}'>",
           f"<title>SoHoT status</title><style>{_CSS}</style></head><body>",
           f"<h1>SoHoT status <span class='asof'>as of {e(_t(r['generated']))} · <a href='status.json'>json</a></span></h1>"]
    if r["banner"]:
        out.append("<div class='banner'><b>Needs you</b><ul>" + "".join(f"<li>{e(b)}</li>" for b in r["banner"]) + "</ul></div>")
    else:
        out.append("<p class='ok'>Nothing needs you.</p>")
    for title, body in lines(r).items():
        asof = r[_KEYS[title]].get("as_of")
        out.append(f"<h2>{e(title)} <span class='asof'>as of {e(time.strftime('%H:%M:%S', time.localtime(asof)) if asof else '?')}</span></h2>")
        out.append("<ul>" + "".join(f"<li>{e(x)}</li>" for x in body) + "</ul>")
    out.append("</body></html>")
    return "\n".join(out)
