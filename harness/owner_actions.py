"""Owner actions on the status page: a fixed list of existing verbs, accepted only from an allowed device (#2116)."""
from __future__ import annotations

import hashlib
import hmac
import html
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
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

WHOIS_TIMEOUT_S = 5.0

#: One allowed device per line in the home: its tailnet stable node id or its full tailnet name. Missing or empty: read-only.
DEVICES = "owner-devices"
AUDIT = "owner-actions.jsonl"
APP_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
#: A request carrying any of these did not come straight from its caller, so its peer address names nobody.
FORWARDED = ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-real-ip", "via")
TAIL = 2000
BODY_MAX = 4096
HELD_BY = "owner: from the status page"
PAUSE_REASONS = ("owner: the machine is needed", "owner: looking into a failure", "owner: maintenance")
_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_JOB = re.compile(r"^\d{1,9}$")
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


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    does: str
    argv: tuple[str, ...]
    offers: Callable[[dict], list[tuple[str, str]]] | None = None

    def verb(self, arg: str) -> list[str]:
        return [arg if w == "{}" else w for w in self.argv]


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
)
BY_NAME = {a.name: a for a in ACTIONS}


def allowed(home: Path | None = None) -> set[str]:
    """The devices that may act, from the home's config; none when there is no list, an error when it cannot be read."""
    from harness import paths
    try:
        text = ((home or paths.home()) / DEVICES).read_text(encoding="utf-8")
    except FileNotFoundError:
        return set()
    return {line.split("#")[0].strip().rstrip(".") for line in text.splitlines()} - {""}


def tailscale_bin(which=None, exists=None) -> str | None:
    return (which or shutil.which)("tailscale") or (APP_BIN if (exists or os.path.exists)(APP_BIN) else None)


def whois(ip: str, run=None, binary: str | None = None) -> dict:
    """The private network's own record of the device at `ip`; LookupError when it cannot be read."""
    exe = binary or tailscale_bin()
    if not exe:
        raise LookupError("no tailscale binary on PATH or in the app bundle")
    try:
        p = (run or subprocess.run)([exe, "whois", "--json", ip], capture_output=True, text=True,
                                    timeout=WHOIS_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LookupError(f"whois did not run: {type(exc).__name__}") from exc
    if p.returncode != 0:
        raise LookupError(f"whois exited {p.returncode}")
    try:
        got = json.loads(p.stdout)
        node = got["Node"]
        return {"id": str(node.get("StableID") or ""), "name": str(node.get("Name") or "").rstrip(".").lower(),
                "user": str((got.get("UserProfile") or {}).get("LoginName") or "")}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LookupError("whois answered no node") from exc


def _binds(ip: str) -> bool:
    with socket.socket(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind((ip, 0))
        except OSError:
            return False
    return True


def is_local(ip: str, binds=None) -> bool:
    """Loopback, or any address this machine holds: a process here is never the owner's device."""
    try:
        a = ipaddress.ip_address(str(ip).split("%")[0])
    except ValueError:
        return True
    a = getattr(a, "ipv4_mapped", None) or a
    return a.is_loopback or a.is_unspecified or (binds or _binds)(str(a))


def caller(peer: str | None, headers, *, home: Path | None = None, lookup=None, local=None) -> tuple[dict | None, str]:
    """(device, "") when the connection's peer is an allowed device, else (None, why)."""
    try:
        allow = allowed(home)
    except (OSError, ValueError) as exc:
        return None, f"the allowed-device list cannot be read: {type(exc).__name__}"
    if not allow:
        return None, "no allowed device is configured: the page is read-only"
    sent = {str(k).lower() for k in headers}
    if sent & set(FORWARDED):
        return None, "a forwarded request: its peer address is not the caller's"
    if not peer:
        return None, "no peer address"
    if (local or is_local)(peer):
        return None, "a request from this machine"
    try:
        who = (lookup or whois)(peer)
    except Exception as exc:  # noqa: BLE001 - any failed lookup is a refusal, never an acceptance
        return None, f"identity lookup unavailable: {exc}"[:200]
    if not isinstance(who, dict):
        return None, "identity lookup unavailable: it named no device"
    if who.get("id") and who["id"] in allow or who.get("name") and who["name"] in {a.lower() for a in allow}:
        return who, ""
    return None, "not an allowed device"


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


def panel_for(peer: str | None, headers, r: dict, *, now: float | None = None, home: Path | None = None,
              lookup=None, local=None) -> str:
    """The panel for an allowed device's page; nothing for every other reader."""
    who, _ = caller(peer, headers, home=home, lookup=lookup, local=local)
    return panel(r, token(peer or "", who, now)) if who else ""


def _refused(code: int, why: str, entry: dict, home: Path | None) -> tuple[int, str]:
    from harness import status_view as sv
    audit({**entry, "outcome": f"refused: {why}"}, home)
    return code, _html("Not done", [f"<p><b>Refused:</b> {sv.esc(why)}.</p>"])


def press(peer: str | None, headers, form: dict, r: dict, *, now: float | None = None, home: Path | None = None,
          lookup=None, local=None, run=None) -> tuple[int, str]:
    """One POST: the first press asks, the second, carrying that press's confirmation, runs the verb once."""
    from harness import status_page
    from harness import status_view as sv
    now = time.time() if now is None else now
    name, arg, nonce = (str(form.get(k) or "") for k in ("action", "arg", "confirm"))
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(now)), "peer": peer or "", "device": "",
             "action": name[:80], "arg": arg[:80], "press": "confirm" if nonce else "first"}
    who, why = caller(peer, headers, home=home, lookup=lookup, local=local)
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
