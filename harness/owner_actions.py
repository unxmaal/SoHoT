"""Owner actions on the status page: a fixed list of existing verbs, accepted from any peer on the connection itself (#2116, #2128)."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import secrets
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CONFIRM_TTL_S = 120.0

TOKEN_TTL_S = 900.0

ACTION_TIMEOUT_S = 120.0

AUDIT = "owner-actions.jsonl"
#: A request carrying any of these did not come straight from its caller, so its peer address names nobody.
FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "via")
TAIL = 2000
BODY_MAX = 4096
HELD_BY = "owner: from the status page"
PAUSE_REASONS = ("owner: the machine is needed", "owner: looking into a failure", "owner: maintenance")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_JOB = re.compile(r"^\d{1,9}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY = secrets.token_bytes(32)
_lock = threading.Lock()
_confirms: dict[str, tuple] = {}


def _shas(r: dict) -> list[tuple[str, str]]:
    d = r.get("deploy") or {}
    got, head = [], str(d.get("head") or "")
    for sha, what in ((d.get("main"), "origin/main"), ((d.get("wait") or {}).get("sha"), "waiting")):
        sha = str(sha or "")
        if _SHA.match(sha) and sha != head and sha not in [s for s, _ in got]:
            got.append((sha, f"{what} {sha[:8]}"))
    return got


def _reasons(r: dict) -> list[tuple[str, str]]:
    return [(x, x) for x in PAUSE_REASONS]


def _sweep_jobs(r: dict) -> list[tuple[str, str]]:
    jobs = ((r.get("discovery") or {}).get("queued") or {}).get("jobs") or []
    return [(str(j["id"]), f"job {j['id']} ({j.get('step')})") for j in jobs if _JOB.match(str(j.get("id") or ""))]


def _jobs(r: dict, states: tuple[str, ...]) -> list[tuple[str, str]]:
    rows = ((r.get("stops") or {}).get("jobs") or {}).get("rows") or []
    return [(str(j["id"]), f"job {j['id']} ({j.get('title')})") for j in rows
            if j.get("state") in states and _JOB.match(str(j.get("id") or ""))]


def _failed_jobs(r: dict) -> list[tuple[str, str]]:
    return _jobs(r, ("failed",))


def _queue_ids(r: dict, key: str) -> list[dict]:
    return [j for j in (r.get("queue") or {}).get(key) or [] if _JOB.match(str(j.get("id") or ""))]


def _cancellable(r: dict) -> list[tuple[str, str]]:
    """Every job the page lists as running, waiting, paused or stuck."""
    got = dict(_jobs(r, ("running", "paused")))
    for key in ("running", "waiting"):
        got.update({str(j["id"]): f"job {j['id']} ({j.get('title')})" for j in _queue_ids(r, key)})
    return sorted(got.items())


def _held_jobs(r: dict) -> list[tuple[str, str]]:
    return [(str(j["id"]), f"job {j['id']} ({j.get('title')})") for j in _queue_ids(r, "waiting") if j.get("held")]


def _raisable(r: dict) -> list[tuple[str, str]]:
    """Each waiting job but the first, paired with the priority one above the highest waiting: `id:priority`."""
    rows = _queue_ids(r, "waiting")
    top = max([int(j.get("priority") or 0) for j in rows] or [0]) + 1
    return [(f"{j['id']}:{top}", f"job {j['id']} ({j.get('title')}) to priority {top}") for j in rows[1:]]


def _rows(r: dict, kind: str, states: tuple[str, ...]) -> list[tuple[str, str]]:
    return [(x["name"], x["name"]) for x in (r.get("features") or {}).get("rows") or []
            if x.get("kind") == kind and x.get("state") in states and _NAME.match(str(x.get("name") or ""))]


def _units(r: dict) -> list[tuple[str, str]]:
    """The units the page lists as loaded, and the stopped ones the Needs-you band names."""
    from harness import needs_you
    names = [n for n in needs_you.unit_names(r) if _NAME.match(n)] + [n for n, _ in _rows(r, "unit", ("on", "on demand", "broken"))]
    return [(n, n) for n in dict.fromkeys(names)]


def _routed_nodes(r: dict) -> list[tuple[str, str]]:
    return _rows(r, "node", ("on",))


def _parked_nodes(r: dict) -> list[tuple[str, str]]:
    return _rows(r, "node", ("parked",))


def _lanes(r: dict) -> list[tuple[str, str]]:
    return _rows(r, "lane", ("on", "on demand"))


def backup_due(r: dict) -> bool:
    """A Postgres store that is up with no daily dump yet today, by the page's own clock."""
    st, day = r.get("store") or {}, time.strftime("%Y%m%d", time.localtime(r.get("generated") or time.time()))
    at = st.get("backup_at")
    return bool(st.get("up") and st.get("backend") == "postgres"
                and not (at is not None and time.strftime("%Y%m%d", time.localtime(at)) == day))


def _gate(r: dict, key: str) -> list[tuple[str, str]]:
    rows = (r.get("lane_gate") or {}).get(key) or []
    return [(g["lane"], f"{g['lane']} (power {g['power']:.2f})") for g in rows if _NAME.match(str(g.get("lane") or ""))]


def _closed_lanes(r: dict) -> list[tuple[str, str]]:
    return _gate(r, "closed")


def _opened_lanes(r: dict) -> list[tuple[str, str]]:
    return _gate(r, "opened")


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    does: str
    argv: tuple[str, ...]
    offers: Callable[[dict], list[tuple[str, str]]] | None = None
    #: The arg is several words joined by ":" (a job id and its new priority).
    split: bool = False

    def verb(self, arg: str) -> list[str]:
        out: list[str] = []
        for w in self.argv:
            out += (arg.split(":") if self.split else [arg]) if w == "{}" else [w]
        return out


ACTIONS = (
    Action("deploy_now", "Deploy now", "queues a deploy of the chosen commit at once", ("deploy", "now", "{}"), _shas),
    Action("benchmarks_hold", "Hold benchmarks", "no sweep, reverify or measurement job starts until released",
           ("hold", "benchmarks", HELD_BY)),
    Action("benchmarks_release", "Release benchmarks", "ends the benchmarks hold", ("hold", "release", "benchmarks")),
    Action("gate_hold", "Hold the gate", "no batch GPU job or deploy starts until released", ("hold", "gpu", HELD_BY)),
    Action("gate_release", "Release the gate", "ends the hold on GPU jobs and deploys", ("hold", "release", "gpu")),
    Action("queue_pause", "Pause the queue", "no queue job starts until resumed",
           ("jobs", "pause", "--reason", "{}"), _reasons),
    Action("queue_resume", "Resume the queue", "queue jobs may start again", ("jobs", "resume")),
    Action("discovery_on", "Continuous discovery on", "queues a sweep's first step; each closed sweep queues the next",
           ("discover", "--loop", "--run", "--jobs")),
    Action("discovery_off", "Continuous discovery off", "cancels the waiting sweep step, so no next sweep is queued",
           ("jobs", "cancel", "{}"), _sweep_jobs),
    Action("job_retry", "Retry job", "queues the failed job's command again as a new job", ("jobs", "retry", "{}"),
           _failed_jobs),
    Action("job_cancel", "Cancel job", "stops the job and records it cancelled", ("jobs", "cancel", "{}"), _cancellable),
    Action("job_let", "Let through the hold", "lets the held job start while benchmarks are held", ("hold", "let", "{}"), _held_jobs),
    Action("job_first", "Run first", "raises the job above every waiting job", ("jobs", "priority", "{}"), _raisable, True),
    Action("gate_again", "Test again", "queues a merge gate pass; trees with only a pending verdict are tested", ("merge-gate", "--queue")),
    Action("unit_restart", "Restart unit", "restarts the unit through scripts/launchd.sh, never unloading it",
           ("unit-restart", "{}"), _units),
    Action("node_park", "Park node", "keeps the node in nodes.yaml but leaves it out of routing, probes and checks",
           ("node-park", "park", "{}"), _routed_nodes),
    Action("node_unpark", "Unpark node", "routes to the node again", ("node-park", "unpark", "{}"), _parked_nodes),
    Action("deploy_pause", "Pause deploys", "queues no deploy until resumed; a deploy already running finishes",
           ("deploy", "pause")),
    Action("deploy_resume", "Resume deploys", "deploys may be queued and start again", ("deploy", "resume")),
    Action("review_off", "Switch the review off", "the weekly review does not run until switched on", ("review", "off")),
    Action("review_on", "Switch the review on", "the weekly review runs when due again", ("review", "on")),
    Action("router_relist", "Relist the router", "restarts the router once so it lists what has a file; refuses when an advertised "
           "id still has its file", ("router", "relist")),
    Action("pg_backup", "Back up the store", "writes today's checked Postgres dump unless one was made today",
           ("store", "pg-backup", "--due")),
    Action("lane_open", "Open lane anyway", "opens a lane the power gate closed to challengers for a while; recorded, and it closes "
           "again at its expiry", ("lane-gate", "open", "{}"), _closed_lanes),
    Action("lane_close", "Close lane again", "ends the open-anyway of a gated lane now", ("lane-gate", "close", "{}"), _opened_lanes),
    Action("lane_reverify", "Reverify lane", "queues a re-run of the lane's served model when a reverify trigger has fired",
           ("reverify", "--lane", "{}"), _lanes),
)
BY_NAME = {a.name: a for a in ACTIONS}


def caller(peer: str | None, headers) -> tuple[dict | None, str]:
    """({"name", "id"}, "") for any peer with its own connection address, else (None, why). #2128."""
    sent = {str(k).lower() for k in headers}
    if sent & set(FORWARDED):
        return None, "a forwarded request: its peer address is not the caller's"
    if not peer:
        return None, "no peer address"
    return {"name": peer, "id": peer}, ""


def _sign(peer: str, device: str, exp: int) -> str:
    return hmac.new(_KEY, f"page|{peer}|{device}|{exp}".encode(), hashlib.sha256).hexdigest()


def token(peer: str, who: dict, now: float | None = None) -> str:
    """A page's token: good for this peer and device until TOKEN_TTL_S passes or the server restarts."""
    exp = int((time.time() if now is None else now) + TOKEN_TTL_S)
    return f"{exp}.{_sign(peer, who.get('id') or who.get('name') or '', exp)}"


def token_ok(tok: str, peer: str, who: dict, now: float | None = None) -> bool:
    exp, _, sig = str(tok or "").partition(".")
    if not exp.isdigit() or int(exp) < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(sig, _sign(peer, who.get("id") or who.get("name") or "", int(exp)))


def audit(entry: dict, home: Path | None = None) -> None:
    from harness import paths
    line = json.dumps(entry, sort_keys=True, default=str) + "\n"
    with _lock, open((home or paths.home()) / AUDIT, "a", encoding="utf-8") as f:
        f.write(line)


def run_verb(argv: list[str], run=None) -> dict:
    """The verb as its own soh process: {rc, out}, rc None when it did not return in time."""
    from harness import paths
    cmd = [sys.executable, "-m", "harness.cli", *argv]
    try:
        p = (run or subprocess.run)(cmd, capture_output=True, text=True, timeout=ACTION_TIMEOUT_S,
                                    stdin=subprocess.DEVNULL, cwd=str(paths.REPO))
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": f"no answer in {ACTION_TIMEOUT_S:.0f} s; soh {' '.join(argv)} may still be running"}
    except OSError as exc:
        return {"rc": None, "out": f"did not start: {exc}"}
    return {"rc": p.returncode, "out": ((p.stdout or "") + (p.stderr or ""))[-TAIL:]}


def _html(title: str, body: list[str]) -> str:
    from harness import status_view as sv
    return "\n".join(["<!doctype html><html><head><meta charset='utf-8'>",
                      "<meta name='viewport' content='width=device-width,initial-scale=1'>",
                      f"<title>SoHoT status</title><style>{sv.CSS}{CSS}</style></head><body>",
                      f"<div class='top'><h1>{sv.esc(title)}</h1></div><div class='panel'>", *body,
                      "<p><a href='../status'>Back to status</a></p></div></body></html>"])


CSS = (".act{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;margin:10px 0 0}.act span{color:var(--ink2);"
       "font-size:13px;flex-basis:100%}.act button,.act select{font:inherit;padding:8px 12px;border-radius:6px;"
       "border:1px solid var(--axis);background:var(--page);color:var(--ink)}pre{white-space:pre-wrap;"
       "overflow-wrap:anywhere;font-size:12px}")


def _attr(v) -> str:
    return html.escape(str(v), quote=True)


def _hidden(**fields) -> str:
    return "".join(f"<input type='hidden' name='{k}' value='{_attr(v)}'>" for k, v in fields.items())


def panel(r: dict, tok: str, post: str = "status/action") -> str:
    """The actions as forms: one first press each, a choice only from what `r` offers."""
    from harness import status_view as sv
    out = [f"<style>{CSS}</style><div class='panel'><h2>Owner actions</h2>"]
    for a in ACTIONS:
        out.append(f"<form class='act' method='post' action='{post}'>{_hidden(token=tok, action=a.name)}")
        offered = a.offers(r) if a.offers else None
        if offered:
            out.append("<select name='arg'>" + "".join(
                f"<option value='{_attr(v)}'>{sv.esc(label)}</option>" for v, label in offered) + "</select>")
        out.append(f"<button{' disabled' if a.offers and not offered else ''}>{sv.esc(a.label)}</button>"
                   f"<span>{sv.esc(a.does)}{'; nothing to choose now' if a.offers and not offered else ''}</span></form>")
    out.append("</div>")
    return "\n".join(out)


def panel_for(peer: str | None, headers, r: dict, *, now: float | None = None, home: Path | None = None) -> str:
    """The panel for a page read from another device; nothing for a forwarded request."""
    who, _ = caller(peer, headers)
    return panel(r, token(peer or "", who, now)) if who else ""


def token_for(peer: str | None, headers, *, now: float | None = None) -> str:
    """The page token for a caller allowed to press, else ''."""
    who, _ = caller(peer, headers)
    return token(peer or "", who, now) if who else ""


def button(action: str, arg: str, tok: str, post: str = "status/action", *, bare: bool = False) -> str:
    """One press of `action` on `arg` from the Needs-you band or a row; the same confirm flow as the panel."""
    from harness import status_view as sv
    a = BY_NAME[action]
    label = f"{a.label} {arg.split(':')[0][:12]}" if arg and not bare else a.label
    return (f"<form class='act' method='post' action='{post}'>{_hidden(token=tok, action=action, **({'arg': arg} if arg else {}))}"
            f"<button title='{_attr(a.does)}'>{sv.esc(label)}</button></form>")


def _refused(code: int, why: str, entry: dict, home: Path | None) -> tuple[int, str]:
    from harness import status_view as sv
    audit({**entry, "outcome": f"refused: {why}"}, home)
    return code, _html("Not done", [f"<p><b>Refused:</b> {sv.esc(why)}.</p>"])


def press(peer: str | None, headers, form: dict, r: dict, *, now: float | None = None, home: Path | None = None,
          run=None) -> tuple[int, str]:
    """One POST: the first press asks, the second, carrying that press's confirmation, runs the verb once."""
    from harness import status_page
    from harness import status_view as sv
    now = time.time() if now is None else now
    name, arg, nonce = (str(form.get(k) or "") for k in ("action", "arg", "confirm"))
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "peer": peer or "", "device": "",
             "action": name[:80], "arg": arg[:80], "press": "confirm" if nonce else "first"}
    who, why = caller(peer, headers)
    if not who:
        return _refused(403, why, entry, home)
    entry.update(device=who.get("name") or who.get("id"), device_id=who.get("id"), user=who.get("user"))
    if not token_ok(str(form.get("token") or ""), peer or "", who, now):
        return _refused(403, "the page token is missing or stale; reload the status page", entry, home)
    action = BY_NAME.get(name)
    if action is None:
        return _refused(400, "not one of the listed actions", entry, home)
    offered = [v for v, _ in action.offers(r)] if action.offers else []
    if (arg not in offered) if action.offers else arg:
        return _refused(400, "the page does not offer that choice now; reload the status page", entry, home)
    verb = action.verb(arg)
    bound = (peer, who.get("id") or who.get("name"), name, arg)
    if not nonce:
        nonce = secrets.token_urlsafe(24)
        with _lock:
            for k in [k for k, v in _confirms.items() if v[1] < now]:
                del _confirms[k]
            _confirms[nonce] = (bound, now + CONFIRM_TTL_S)
        audit({**entry, "outcome": "asked to confirm"}, home)
        return 200, _html(action.label, [
            f"<p>This {sv.esc(action.does)}.</p><pre>soh {_attr(' '.join(verb))}</pre>",
            f"<form class='act' method='post' action='action'>"
            f"{_hidden(token=form.get('token'), action=name, arg=arg, confirm=nonce)}"
            f"<button>Confirm: {sv.esc(action.label)}</button></form>"])
    with _lock:
        held = _confirms.pop(nonce, None)
    if held is None or held[0] != bound or held[1] < now:
        return _refused(409, "that confirmation was already used or has expired; nothing ran", entry, home)
    got = run_verb(verb, run)
    status_page.forget()
    audit({**entry, "outcome": "timed out" if got["rc"] is None else f"rc {got['rc']}"}, home)
    out = status_page.scrub(got["out"], status_page._secret_values(home=home))
    ok = got["rc"] == 0
    return 200, _html(action.label, [
        f"<p><b>{'Done' if ok else 'Failed'}:</b> soh {sv.esc(' '.join(verb))} "
        f"{'did not return' if got['rc'] is None else 'exited ' + str(got['rc'])}.</p><pre>{sv.esc(out)}</pre>"])
