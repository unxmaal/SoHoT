"""The status page's Needs-you band: every condition that stops work, and the alert when one starts or clears (#2134)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from harness import atomic_file

#: Seconds a failed job stays in the band, unless a later job of its title has run since.
FAILED_WINDOW_S = 86400.0
#: Seconds a paused job may sit before the band names it; the queue puts the rest back itself.
PAUSED_GRACE_S = 3600.0
#: Passes in a row a condition must be gone before its clearing is alerted.
CLEAR_PASSES = 2
#: Monit alert kinds that name a stop of their own: the others have their section (store, deploy) or are not stops.
MONIT_KINDS = ("memory", "disk", "disk-pause", "volume", "volume-low")
KIND = "needs-you"
SERVICE = "needs-you/"
STATE = "needs-you.json"


def cond(key: str, title: str, why: str, *, since=None, fix=(), none: str = "", source: str = "", alert: bool = True,
         line: str = "") -> dict:
    """One thing that stops work: `fix` is the (action, arg) buttons that clear it, `none` says why there is no button."""
    return {"key": key, "title": title, "why": why, "since": since, "fix": [{"action": a, "arg": g} for a, g in fix],
            "none": none, "source": source, "alert": alert, "line": line or (f"{title}: {why}" if why else title)}


def read_holds(conn, now: float) -> dict:
    from harness import hold
    if conn is None:
        return {"rows": [], "why": "store down: holds not read"}
    return {"rows": [{k: h.get(k) for k in ("kind", "said", "held_at", "until")} for h in hold.actives(conn, now)]}


def read_jobs(conn, now: float) -> dict:
    """Failed jobs not run again since, running jobs past every watchdog limit, and paused jobs, as the jobs table says."""
    from harness import deploy, watchdog
    from harness import workqueue as wq
    if conn is None:
        return {"rows": [], "why": "store down: jobs not read"}
    here, args = wq._claimed(conn)
    live = (wq.PENDING, wq.RUNNING, wq.DONE)
    rows = conn.execute(
        "SELECT id, title, kind, state, note, reason, rc, started_at, finished_at FROM jobs "
        f"WHERE {here} AND ((state = ? AND finished_at >= ? AND kind != ? AND NOT EXISTS "
        "(SELECT 1 FROM jobs n WHERE n.title = jobs.title AND n.id > jobs.id AND n.state IN (?, ?, ?))) "
        "OR state IN (?, ?)) ORDER BY id",
        (*args, wq.FAILED, now - FAILED_WINDOW_S, deploy.KIND, *live, wq.RUNNING, wq.PAUSED)).fetchall()
    limit = max(watchdog.long_run_limits().values())
    out = []
    for r in rows:
        began = r["started_at"] or r["finished_at"]
        if r["state"] == wq.RUNNING and (not began or now - float(began) <= limit):
            continue
        if r["state"] == wq.PAUSED and (not began or now - float(began) <= PAUSED_GRACE_S):
            continue
        out.append({"id": wq.label(r["id"]), "title": r["title"], "kind": r["kind"], "state": r["state"],
                    "why": r["note"] or r["reason"] or (f"exited {r['rc']}" if r["rc"] is not None else ""),
                    "at": r["finished_at"] if r["state"] == wq.FAILED else began, "limit_s": limit})
    return {"rows": out}


def read_gateway() -> dict:
    from harness import gateway_degraded
    return {"mark": gateway_degraded.read()}


#: Monit states that mean the service passes now; "not monitored" and "initializing" say nothing either way.
_MONIT_PASSING = re.compile(r"^(ok|running|accessible|online.*|status ok)$", re.I)


def read_monit(now: float, home: Path | None = None, live: dict | None = None) -> dict:
    """The monit alerts still open in the log whose service monit does not now report passing. #2143."""
    from harness import monitor
    live = live or {}
    state = {c["check"]: bool(_MONIT_PASSING.match(c["state"])) for c in live.get("checks") or [] if live.get("running")}
    return {"open": [{k: a.get(k) for k in ("at", "kind", "service", "description")}
                     for a in monitor.still_open(monitor.alerts(0, home)) if not state.get(a.get("service"), False)]}


def _age(t, now: float) -> str:
    return "" if not t else f"{max(0.0, now - float(t)) / 3600:.1f} h"


def unit_names(r: dict) -> list[str]:
    """The units the page may restart: each one features says is broken, the gateway while marked degraded, a monit service that is down."""
    names = [x["name"] for x in (r.get("features") or {}).get("rows") or [] if x["kind"] == "unit" and x["state"] == "broken"]
    if ((r.get("stops") or {}).get("gateway") or {}).get("mark") is not None:
        names.append("gateway")
    names += [a["service"].removeprefix("service_") for a in ((r.get("stops") or {}).get("monit") or {}).get("open") or []
              if a["kind"] == "service" and str(a["service"]).startswith("service_")]
    return list(dict.fromkeys(names))


def _release(scope: str) -> str:
    return "benchmarks_release" if scope == "benchmarks" else "gate_release"


def _holds(r: dict) -> list[dict]:
    from harness import hold
    out = []
    for h in (r.get("stops") or {}).get("holds", {}).get("rows") or []:
        what = ("Benchmarks held: no sweep, reverify or measurement job starts" if h["kind"] == hold.BENCHMARKS
                else "The GPU gate is held: no batch GPU job or deploy starts")
        until = f", until {hold._at(h['until'])}" if h.get("until") else ""
        out.append(cond(f"hold-{h['kind']}", what, f"{h['said']}{until}", since=h["held_at"], source="holds",
                        fix=[(_release(h["kind"]), "")]))
    return out


def _queue(r: dict) -> list[dict]:
    q = r["queue"]
    if q.get("error") or not q.get("paused"):
        return []
    who = f" ({q['who']})" if q.get("who") else ""
    held = q.get("deploy_hold")
    if held and held["live"]:
        return []
    since = q.get("paused_since")
    title = "The queue is paused: no job starts"
    if held:
        title = "A deploy's queue pause is stuck: its process is gone"
    return [cond("queue-paused", title, f"{q.get('reason')}{who}",
                 since=since, source="queue", fix=[("queue_resume", "")],
                 line=f"queue paused {_age(since, r['generated'])}: {q.get('reason')}")]


def _discovery(r: dict, held: bool) -> list[dict]:
    from harness import status_page as sp
    d, now = r["discovery"], r["generated"]
    if d.get("error"):
        return []
    on = [("discovery_on", "")]
    queued = bool(((d.get("queued") or {}).get("jobs")))
    out = []
    if d.get("status") == "stalled":
        since = now - float(d["age_s"]) if d.get("age_s") is not None else d.get("started")
        wait = ", ".join(f"job {j['id']}" for j in (d.get("queued") or {}).get("jobs") or [])
        out.append(cond("discovery-stalled", "The discovery loop has stalled", d.get("line") or "", since=since,
                        source="discovery", fix=[] if queued else on, line=f"discovery stalled: {d.get('line')}",
                        none=f"a restart is queued ({wait}); it starts when the queue reaches it" if queued else ""))
    elif sp.discovery_failed(d) and not held and not queued:
        why = d.get("failure") or f"rc {d.get('rc')}"
        out.append(cond("discovery-failed", "The discovery loop failed", why, since=d.get("finished"),
                        source="discovery", fix=on, line=f"discovery failed: {why}"))
    if d.get("overdue") and d.get("status") != "stalled" and not held and not queued:
        out.append(cond("discovery-off", "Discovery is not running on its schedule", d["overdue"], since=d.get("started"),
                        source="discovery", fix=on, line=f"discovery overdue: {d['overdue']}"))
    sp_ = d.get("spend") or {}
    if sp.spend_stalled(sp_, now) and not held:
        out.append(cond("discovery-screens-nothing", "Discovery screens nothing",
                        f"no screen or measure since {sp._t(sp_.get('last_run_at'))} while {sp_['waiting']} candidate(s) wait",
                        since=sp_.get("last_run_at"), source="discovery", fix=on,
                        line=f"discovery screens nothing: no screen or measure since {sp._t(sp_.get('last_run_at'))} "
                             f"while {sp_['waiting']} candidate(s) wait"))
    return out


def _jobs(r: dict) -> list[dict]:
    out = []
    for j in (r.get("stops") or {}).get("jobs", {}).get("rows") or []:
        what = f"job {j['id']} ({j['kind']}: {j['title']})"
        if j["state"] == "failed":
            out.append(cond(f"job-failed-{j['id']}", f"A job failed: {what}", j["why"], since=j["at"], source="jobs",
                            fix=[("job_retry", j["id"])]))
        elif j["state"] == "running":
            out.append(cond(f"job-stuck-{j['id']}", f"A job is stuck: {what}",
                            f"running past the watchdog's longest limit, {j['limit_s'] / 3600:.0f} h", since=j["at"],
                            source="jobs", fix=[("job_cancel", j["id"])]))
        else:
            out.append(cond(f"job-paused-{j['id']}", f"A job is paused: {what}", j["why"], since=j["at"], source="jobs",
                            fix=[("job_cancel", j["id"])]))
    return out


def _deploy(r: dict) -> list[dict]:
    from harness import contention, owner_actions
    from harness import deploy as deploys
    d, now = r["deploy"], r["generated"]
    if d.get("error"):
        return []
    sha = next(iter(owner_actions._shas(r)), ("", ""))[0]
    now_btn = [("deploy_now", sha)] if sha else []
    out = []
    if d.get("failing"):
        last = d.get("last") or {}
        out.append(cond("deploy-failing", "Deploys are failing", f"{d['failing']} in a row, last {last.get('line') or last.get('outcome')}",
                        since=last.get("at"), source="deploy", fix=now_btn,
                        line=f"deploy failing: {d['failing']} in a row, last {last.get('line') or last.get('outcome')}"))
    w = d.get("wait")
    if w and w.get("why") and w["waited"] >= contention.DEPLOY_ALERT_S:
        pause = [("queue_resume", "")] if w.get("pause") else []
        out.append(cond("deploy-blocked", "A deploy is blocked", deploys.blocked_line(w, now)[1], since=w["since"],
                        source="deploy", fix=pause + now_btn,
                        none="" if pause or now_btn else "it waits on the hold or the running job named, and starts once that ends"))
    return out


def _gateway(r: dict) -> list[dict]:
    mark = ((r.get("stops") or {}).get("gateway") or {}).get("mark")
    if mark is None:
        return []
    return [cond("gateway-degraded", "The gateway serves no lane aliases",
                 f"it runs the base config: {mark.get('reason', '')}", since=mark.get("at"), source="gateway",
                 fix=[("unit_restart", "gateway")])]


def _monit(r: dict) -> list[dict]:
    out = []
    for a in ((r.get("stops") or {}).get("monit") or {}).get("open") or []:
        svc, kind = str(a["service"]), a["kind"]
        if kind == "service" and svc.startswith("service_"):
            out.append(cond(f"service-{svc}", f"{svc.removeprefix('service_')} is not answering", a["description"] or "",
                            since=a["at"], source="monit", fix=[("unit_restart", svc.removeprefix("service_"))]))
        elif kind in MONIT_KINDS:
            out.append(cond(f"monit-{svc}", "Memory pressure is high" if kind == "memory" else f"{svc} needs attention",
                            a["description"] or "", since=a["at"], source="monit",
                            none="it clears when the load ends; GPU jobs and deploys wait for it" if kind == "memory"
                            else "free space on that volume, then it clears"))
    return out


def _machine(r: dict) -> list[dict]:
    s, mon, sv = r["store"], r["monitor"], r["services"]
    out = []
    if not s.get("up") and not s.get("error"):
        out.append(cond("store-down", "The store is down", s.get("why") or "unreachable", source="store",
                        line=f"store down: {s.get('why') or 'unreachable'}", none="the store runs as its own service; start it from the machine"))
    if mon.get("error"):
        out.append(cond("monit-unread", "Monit was not read", mon["error"], source="monitor", alert=False,
                        line=f"monitor not read: {mon['error']}"))
    elif not mon.get("running"):
        why = "; ".join(mon.get("problems") or ["no checks run"])
        out.append(cond("monit-down", "Monit is not running", why, source="monitor", line=f"monit is not running: {why}",
                        none="nothing watches the machine until `soh monitor install` runs on it"))
    out += [cond(f"check-{c['check']}", f"Check {c['check']} is {c['state']}", "", source="monitor",
                 line=f"check {c['check']} is {c['state']}", none="its monit check says so; it clears when the check passes") for c in mon.get("checks") or [] if not c["ok"]]
    out += [cond(f"unit-{x['name']}", f"The {x['name']} unit is down", x["by"], since=x.get("since"), source="features",
                 fix=[("unit_restart", x["name"])]) for x in (r.get("features") or {}).get("rows") or []
            if x["kind"] == "unit" and x["state"] == "broken"]
    out += [cond(f"node-{n['node']}", f"Node {n['node']} is down", f"out {n['down_s'] / 60:.0f} min in the last 24 h",
                 source="services", none="it is another machine: check its power and network",
                 line=f"node {n['node']} is down") for n in sv.get("nodes") or [] if n["down_now"]]
    lane = sv.get("lane") or {}
    if lane.get("generating") is False:
        why = lane.get("why") or lane.get("base") or ""
        out.append(cond("lane-cannot-generate", f"The {lane.get('lane')} lane cannot generate", why, source="services",
                        line=f"the {lane.get('lane')} lane cannot generate: {why}", none="the watchdog restarts the mlx unit"))
    return out


def conditions(r: dict) -> list[dict]:
    """Every condition that stops work in the gathered status `r`, oldest first; each from the source its CLI reads."""
    held = bool(_holds_of(r, "benchmarks"))
    out = (_machine(r) + _holds(r) + _queue(r) + _discovery(r, held) + _jobs(r) + _deploy(r) + _gateway(r) + _monit(r))
    out += [cond(f"unread-{k}", f"{k.capitalize()} was not read", r[k]["error"], source=k, alert=False,
                 line=f"{k} not read: {r[k]['error']}") for k in ("store", "queue", "deploy", "discovery", "services", "ratio",
                                                                  "timeline") if (r.get(k) or {}).get("error")]
    out += [cond(f"unread-{k}", f"{k.capitalize()} was not read", v["error"], source=k, alert=False,
                 line=f"{k} not read: {v['error']}") for k, v in (r.get("stops") or {}).items() if v.get("error")]
    return sorted(out, key=lambda c: (c["since"] is None, c["since"] or 0))


def _holds_of(r: dict, kind: str) -> list[dict]:
    return [h for h in ((r.get("stops") or {}).get("holds") or {}).get("rows") or [] if h["kind"] == kind]


def unread(r: dict) -> set[str]:
    """Condition sources this gather could not read: what they would show is not known to be gone."""
    return {k for k, v in {**r, **(r.get("stops") or {})}.items() if isinstance(v, dict) and (v.get("error") or v.get("why"))}


def state_path(home: Path | None = None) -> Path:
    from harness import monitor
    return monitor.state_dir(home) / STATE


def _load(home: Path | None) -> dict:
    """The sources and missed passes of the conditions last seen; {} only when no pass has written the file yet."""
    path = state_path(home)
    if not path.exists():
        return {}
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} is not readable JSON, so the Needs-you pass cannot tell what it already alerted: {exc}") from exc
    if not isinstance(got, dict):
        raise ValueError(f"{path} holds a {type(got).__name__}, not the dict of open conditions")
    return got


def sync(r: dict, home: Path | None = None, *, send=None) -> dict:
    """Alert each condition once as it begins and once as it clears; the monit alert log is the record of what is open.

    A condition whose source this gather could not read keeps its state, and one that vanishes clears only after
    CLEAR_PASSES passes in a row, so one odd read neither clears nor re-opens it."""
    from harness import monitor
    send = send or monitor.alert
    now = r["generated"]
    have = {c["key"]: c for c in conditions(r) if c["alert"]}
    opened = {str(a["service"]).removeprefix(SERVICE): a for a in monitor.still_open(monitor.alerts(0, home))
              if a.get("kind") == KIND and str(a.get("service")).startswith(SERVICE)}
    blind, kept = unread(r), _load(home)
    state, began, cleared = {}, [], []
    for key, c in have.items():
        state[key] = {"source": c["source"], "missed": 0}
        if key not in opened:
            send(KIND, {"MONIT_SERVICE": SERVICE + key, "MONIT_EVENT": "began", "MONIT_DESCRIPTION": _text(c, now)}, home=home)
            began.append(key)
    for key, a in opened.items():
        if key in have:
            continue
        old = kept.get(key) or {}
        if old.get("source") in blind:
            state[key] = old
            continue
        missed = int(old.get("missed") or 0) + 1
        if missed < CLEAR_PASSES:
            state[key] = {"source": old.get("source"), "missed": missed}
            continue
        send(monitor.RECOVERED, {"MONIT_SERVICE": SERVICE + key, "MONIT_EVENT": "cleared",
                                 "MONIT_DESCRIPTION": f"{a.get('description') or key}: no longer stopped"}, home=home)
        cleared.append(key)
    path = state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    atomic_file.replace(tmp, path)
    return {"began": began, "cleared": cleared, "open": sorted(have), "at": now}


def _text(c: dict, now: float) -> str:
    since = f" since {time.strftime('%m-%d %H:%M', time.localtime(float(c['since'])))}" if c["since"] else ""
    fix = ("; press " + ", ".join(f["action"].replace("_", " ") for f in c["fix"]) + " on the status page") if c["fix"] else ""
    return f"{c['title']}{since}: {c['why']}{fix}"[:500]
