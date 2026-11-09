"""Each watchdog wake asks every resident text lane a known-answer completion on its delegation route and records the outcome in lane_probes (#924)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

UP, DOWN, SLOW, SKIPPED = "up", "down", "slow", "skipped"
OUTCOMES = (UP, DOWN, SLOW, SKIPPED)

PROMPT = "Reply with exactly: OK"
_OK = re.compile(r"\bOK\b", re.I)
DECIDE_PROMPT = "Is the sky blue on a clear day? A: yes, B: no. Reply as JSON."
DECIDE_FORMAT = {"type": "json_schema", "json_schema": {"name": "decide", "strict": True, "schema": {
    "type": "object", "properties": {"answer": {"type": "string", "enum": ["A", "B"]}},
    "required": ["answer"], "additionalProperties": False}}}
CLAIMS_PROMPT = "[1] member-a: The fan runs at 12V."
CLAIMS_FORMAT = {"type": "json_schema", "json_schema": {"name": "claims", "strict": True, "schema": {
    "type": "object", "properties": {"c": {"type": "array", "items": {
        "type": "array", "prefixItems": [{"type": "string"}, {"type": "string", "maxLength": 220},
                                         {"type": "array", "items": {"type": "integer"}, "minItems": 1}],
        "minItems": 3, "maxItems": 3}}}, "required": ["c"], "additionalProperties": False}}}

#: Reply tokens a probe allows; the schema lanes write JSON, so they need more than "OK".
MAX_TOKENS = {"decide": 20, "claims": 100}
MAX_TOKENS_DEFAULT = 8
#: Seconds a probe waits before it reads as slow; the 35B code and agent lanes get longer than the small ones.
TIMEOUT_S = {"code": 60.0, "agent": 60.0, "claims": 60.0}
TIMEOUT_DEFAULT_S = 30.0
#: Seconds a slow probe's request is left to finish before its sender gives up on it.
HOLD_S = 1800.0
#: Characters of a server's error kept on the row.
ERROR_CHARS = 300
#: Seconds a lane's open incident may go with no up or down row before a night wake sends one probe that loads it (#1499).
UNPROBED_S = 24 * 3600.0
#: How a deliberate probe's reason starts; the next one waits UNPROBED_S after it.
DELIBERATE = "a deliberate night probe"

COLUMNS = ("at", "machine_id", "lane", "spec", "base", "upstream", "model", "engine", "outcome", "reason",
           "http_status", "error", "seconds", "prompt_tokens", "completion_tokens")


def max_tokens(lane: str) -> int:
    return int(MAX_TOKENS.get(lane, MAX_TOKENS_DEFAULT))


def timeout(lane: str) -> float:
    return float(TIMEOUT_S.get(lane, TIMEOUT_DEFAULT_S))


def request(lane: str, model: str) -> dict:
    """The chat completion body a probe of `lane` sends to `model`."""
    prompt, fmt = {"decide": (DECIDE_PROMPT, DECIDE_FORMAT), "claims": (CLAIMS_PROMPT, CLAIMS_FORMAT)}.get(
        lane, (PROMPT, None))
    body = {"model": model, "max_tokens": max_tokens(lane), "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "chat_template_kwargs": {"enable_thinking": False}}
    if fmt:
        body["response_format"] = fmt
    return body


def passes(lane: str, content: str) -> bool:
    """Whether a reply's content is the known answer, not merely a 200."""
    content = (content or "").strip()
    if lane not in ("decide", "claims"):
        return bool(_OK.search(content))
    try:
        got = json.loads(content)
    except ValueError:
        return False
    if lane == "decide":
        return isinstance(got, dict) and got.get("answer") == "A"
    return isinstance(got, dict) and isinstance(got.get("c"), list)


def judge(lane: str, sent: dict) -> dict:
    """outcome, http_status, error and token counts from what the sender saw."""
    status, text = sent.get("status"), sent.get("body") or ""
    out = {"http_status": status, "error": "", "prompt_tokens": None, "completion_tokens": None}
    if status is None:
        out.update(outcome=SLOW if sent.get("timed_out") else DOWN, error=str(sent.get("error") or "no answer"))
        return out
    try:
        body = json.loads(text)
    except ValueError:
        body = None
    if status != 200:
        out.update(outcome=DOWN, error=text.strip() or f"HTTP {status}")
        return out
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        out.update(prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
    try:
        content = body["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        out.update(outcome=DOWN, error=f"no completion in the reply: {text.strip()[:200] or 'empty body'}")
        return out
    if passes(lane, content):
        out["outcome"] = UP
    else:
        out.update(outcome=DOWN, error=f"not the known answer: {content.strip()[:200] or 'empty content'}")
    return out


# --- the sender: a child process, so a request the wake gave up on can finish without blocking the next ---------

def _take(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _sohot(headers) -> dict:
    """The gateway's x-sohot-* reply headers, which name the node or fallback that answered."""
    return {k.lower(): v for k, v in (headers or {}).items() if k.lower().startswith("x-sohot-")}


def _send(req: dict) -> dict:
    """POST req["body"] to req["url"] and wait up to req["hold"]; what came back."""
    import socket
    import urllib.error
    import urllib.request
    data = json.dumps(req["body"]).encode()
    r = urllib.request.Request(req["url"], data=data, method="POST",
                               headers={"Content-Type": "application/json", **req.get("headers", {})})
    started = time.perf_counter()
    out: dict = {"status": None, "body": "", "error": "", "timed_out": False}
    try:
        with urllib.request.urlopen(r, timeout=req["hold"]) as got:
            out.update(status=got.status, body=got.read().decode("utf-8", "replace"), headers=_sohot(got.headers))
    except urllib.error.HTTPError as exc:
        out.update(status=exc.code, body=exc.read().decode("utf-8", "replace"), headers=_sohot(exc.headers))
    except (TimeoutError, socket.timeout) as exc:
        out.update(error=f"no answer after {req['hold']:.0f}s: {exc}", timed_out=True)
        from harness import cuts
        cuts.cut("lane_probe_hold", f"a probe request to {req['url']} given up", value=req["hold"], kept=0, dropped=1)
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
    out["seconds"] = round(time.perf_counter() - started, 4)
    return out


def child(stdin=None) -> int:
    """The sender's body: hold the lane's lock while the request is out, then leave the result beside it."""
    req = json.load(stdin or sys.stdin)
    fd = os.open(req["lock"], os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if not _take(fd):
            return 3
        got = _send(req)
        tmp = Path(req["result"] + ".tmp")
        tmp.write_text(json.dumps(got), encoding="utf-8")
        os.replace(tmp, req["result"])
    finally:
        os.close(fd)
    return 0


class Sender:
    """Starts one child per probe; a child still out when its wait ends is left running and holds the lane's lock."""

    def __init__(self, state: Path, python: str | None = None):
        self.state = Path(state)
        self.python = python or sys.executable
        self.left: list = []

    def _paths(self, lane: str) -> tuple[Path, Path]:
        self.state.mkdir(parents=True, exist_ok=True)
        return self.state / f"probe-{lane}.lock", self.state / f"probe-{lane}.json"

    def in_flight(self, lane: str) -> bool:
        lock, _ = self._paths(lane)
        fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if not _take(fd):
                return True
        finally:
            os.close(fd)
        return False

    def start(self, lane: str, url: str, headers: dict, body: dict, hold: float):
        lock, result = self._paths(lane)
        result.unlink(missing_ok=True)
        req = {"url": url, "headers": headers, "body": body, "hold": hold, "lock": str(lock), "result": str(result)}
        kw = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
              else {"start_new_session": True})
        proc = subprocess.Popen([self.python, "-I", str(Path(__file__).resolve()), "send"], stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        proc.stdin.write(json.dumps(req).encode())
        proc.stdin.close()
        return proc, result

    def collect(self, handle, wait: float) -> dict | None:
        """What the server answered, or None when it had not answered within `wait` seconds."""
        proc, result = handle
        try:
            rc = proc.wait(timeout=max(0.0, wait))
        except subprocess.TimeoutExpired:
            self.left.append(proc)
            return None
        try:
            return json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"status": None, "error": f"the probe's sender exited {rc} with no result", "failed": True}


# --- one wake ---------------------------------------------------------------------------------------------------

def _resolve(lane: str):
    from harness import delegate
    return delegate.route(lane)


def _resident(where, get=None, config=None):
    """(True/False/None, error): delegate.loaded, keeping the exception it would swallow."""
    from harness import delegate
    seen: list = []

    def asking(url):
        try:
            return (get or delegate._get_json)(url)
        except Exception as exc:
            seen.append(exc)
            raise
    got = delegate.loaded(where, get=asking, config=config)
    return got, (seen[0] if seen else None)


def _node(where) -> dict | None:
    """The node a gateway alias goes to first, its @local twin's base and the key the gateway sends it; None for no node. #1653."""
    from harness import completion, context, gateway, nodes, serving
    if not completion.is_gateway(serving.bare(where.base)):
        return None
    entry = context._entry_for(where.model) or {}
    if not entry.get(nodes.NODE_KEY):
        return None
    name = str(entry[nodes.NODE_KEY])
    twin = (context._entry_for(where.model + nodes.LOCAL_SUFFIX) or {}).get("litellm_params") or {}
    try:
        found = next((n for n in nodes.load() if n.name == name), None)
    except ValueError:
        found = None
    return {"name": name, "engine": str(entry.get(serving.ENGINE_KEY) or ""),
            "key": context._key(where.model) or (nodes.secret(found) if found else ""),
            "twin": serving.bare(str(twin.get("api_base") or "")), "alias": where.model + nodes.LOCAL_SUFFIX,
            "config": gateway.served_path()}


def _node_resident(node):
    """A residency check that asks the node itself, with its key, as the served config names it."""
    from harness import context

    def resident(where):
        return _resident(where, get=lambda url: context._get_json(url, node["key"]), config=node["config"])
    return resident


def _refused(exc) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, ConnectionRefusedError) or isinstance(exc, ConnectionRefusedError)


def _timed_out(exc) -> bool:
    import socket
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (TimeoutError, socket.timeout)) or isinstance(exc, (TimeoutError, socket.timeout))


_MINE = "(machine_id = ? OR (machine_id IS NULL AND ? IS NULL))"


#: Step and horizon of the scan for where tonight ends and the next night begins.
_SCAN_STEP_S = 300.0
_SCAN_SPAN_S = 2 * 86400.0


def _lands_by_day(deadline: float, now: float, day) -> bool:
    """Whether `deadline` falls in the day after tonight, when no deliberate probe may load, so tonight is its last chance. #1533."""
    t = now
    while not day(t):
        t += _SCAN_STEP_S
        if t - now > _SCAN_SPAN_S:
            return False
    ends = t
    while day(t):
        t += _SCAN_STEP_S
        if t - now > _SCAN_SPAN_S:
            return False
    return ends <= deadline <= t


def due(conn, lane: str, machine_id, now: float, day=None) -> str:
    """Why this wake may load `lane`'s model: at night, its open incident unprobed past UNPROBED_S, or past it by tomorrow's day; else ""."""
    if conn is None:
        return ""
    if day is None:
        from harness.watchdog import daytime as day
    if day(now):
        return ""
    last = conn.execute(f"SELECT outcome, at FROM lane_probes WHERE lane = ? AND {_MINE} AND outcome IN (?, ?) "
                        "ORDER BY at DESC, id DESC LIMIT 1", (lane, machine_id, machine_id, UP, DOWN)).fetchone()
    if last is None or last["outcome"] != DOWN:
        return ""
    tried = conn.execute(f"SELECT MAX(at) AS at FROM lane_probes WHERE lane = ? AND {_MINE} AND reason LIKE ?",
                         (lane, machine_id, machine_id, DELIBERATE + "%")).fetchone()
    since = max(last["at"], tried["at"] if tried and tried["at"] is not None else last["at"])
    if now - since < UNPROBED_S and not _lands_by_day(since + UNPROBED_S, now, day):
        return ""
    return (f"{DELIBERATE}: last down {time.strftime('%m-%d %H:%M', time.localtime(last['at']))}, "
            f"no up or down for {(now - last['at']) / 3600:.0f} h")


def _level():
    from harness import pressure
    return pressure.sample().level


def prepare(lane: str, sender: Sender, resolve=None, resident=None, busy=None, headers=None, load="", level=None):
    """(row, request): a finished row when no completion may be sent, else the row so far and what to send; `load` may load a cold model."""
    from harness import delegate, serving
    row = {"lane": lane, "spec": "", "base": "", "upstream": "", "model": "", "engine": "", "reason": "",
           "http_status": None, "error": "", "seconds": None, "prompt_tokens": None, "completion_tokens": None}

    def done(outcome, reason, error=""):
        return {**row, "outcome": outcome, "reason": reason[:ERROR_CHARS], "error": error[:ERROR_CHARS]}, None
    try:
        row["spec"], where = (resolve or _resolve)(lane)
        row["base"], row["model"] = serving.bare(where.base), where.model
        row["upstream"], _ = delegate.upstream(where)
        node = _node(where)
        row["engine"] = (node and node["engine"]) or (
            (serving.engine_at(row["upstream"]) or "") if row["upstream"] else "")
    except Exception as exc:  # noqa: BLE001 - a lane with no route is a skipped probe, said why
        return done(SKIPPED, f"no route: {type(exc).__name__}: {exc}")
    if not row["upstream"]:
        return done(SKIPPED, f"the gateway config names no server for {where.model}")
    if sender.in_flight(lane):
        return done(SKIPPED, "the previous probe of this lane has not returned")
    # This machine's lock says nothing about a server on another host, as delegate._gate holds.
    try:
        held = (busy or (lambda: delegate.held_now("lane probe")))() if serving.loopback(row["upstream"]) else ""
    except delegate.Refused as exc:
        return done(SKIPPED, str(exc))
    if held:
        return done(SKIPPED, f"the machine is held: {held}")
    loaded, exc = (resident or (_node_resident(node) if node else _resident))(where)
    if node and loaded is None and exc is not None and (_refused(exc) or _timed_out(exc)):
        # The gateway falls back to the @local twin, so the probe still goes through it and the reply names who answered.
        row["reason"] = f"node {node['name']} did not answer its residency query: {getattr(exc, 'reason', exc)}"[
            :ERROR_CHARS]
        loaded = True
    if loaded is None and exc is not None and _refused(exc):
        return done(DOWN, "the server refused the residency query; no completion sent",
                    f"{row['upstream']}: {getattr(exc, 'reason', exc)}")
    if loaded is None and exc is not None and _timed_out(exc):
        return done(SLOW, "the residency query timed out; no completion sent", str(exc))
    if loaded is False and load and serving.loopback(row["upstream"]):
        from harness.pressure import NORMAL
        got = (level or _level)()
        if got is not None and got > NORMAL:
            return done(SKIPPED, f"the model is not resident and memory pressure is level {got}; {load} waits")
        row["reason"] = load[:ERROR_CHARS]
    elif loaded is not True:
        why = "residency unknown" if loaded is None else "the model is not resident"
        return done(SKIPPED, f"{why}; a probe would load it" + (f" ({type(exc).__name__}: {exc})" if exc else ""))
    if headers is None:
        from harness import gateway_key, purpose
        with purpose.using(purpose.WATCHDOG):
            headers = gateway_key.headers()
    return row, {"url": f"{row['base']}/v1/chat/completions", "headers": headers,
                 "body": request(lane, where.model), "gateway": _via_gateway(where.base), "node": node}


def _served_by(row: dict, sent: dict, node: dict) -> dict:
    """The row naming the node the gateway reached, or the @local twin that answered for it."""
    got = {k.lower(): v for k, v in (sent.get("headers") or {}).items()}
    twin = f"{node['alias']} at {node['twin'] or 'no base'}"
    if got.get("x-sohot-fallback"):
        why, row = f"the {twin} fallback answered; node {node['name']} did not", {**row, "upstream": node["twin"]}
    elif got.get("x-sohot-node"):
        why = f"served by node {got['x-sohot-node']}; fallback {twin}"
    else:
        why = f"the gateway named neither node {node['name']} nor its fallback {twin}"
    return {**row, "reason": _after(row, why)}


def _via_gateway(base: str) -> bool:
    from harness import completion
    return completion.is_gateway(base)


def _after(row: dict, why: str) -> str:
    return "; ".join(w for w in (row.get("reason"), why) if w)[:ERROR_CHARS]


def finish(row: dict, sent: dict | None, wait: float, node: dict | None = None) -> dict:
    if sent is not None and node and not sent.get("failed") and sent.get("status") is not None:
        row = _served_by(row, sent, node)
    if sent is None:
        return {**row, "outcome": SLOW, "seconds": wait,
                "reason": _after(row, f"no answer in {wait:g}s; the request is left to finish, and this lane is not "
                                      "probed again until it does")}
    if sent.get("failed"):
        return {**row, "outcome": SKIPPED, "reason": _after(row, str(sent["error"]))}
    row = {**row, **judge(row["lane"], sent), "seconds": sent.get("seconds")}
    row["error"] = (row["error"] or "")[:ERROR_CHARS]
    return row


def _direct_row(row: dict, at: float) -> dict:
    from harness import purpose, usage
    sent = row.pop("_direct")
    err = None if row["outcome"] == UP else RuntimeError(row["error"])
    if err is not None:
        err.failure_class = str(row["http_status"] or "")
    got = {"prompt_tokens": row["prompt_tokens"], "completion_tokens": row["completion_tokens"],
           "seconds": sent.get("seconds")}
    return {**usage.direct_row(row["lane"], row["spec"], row["model"], at, got, error=err, tag=purpose.WATCHDOG),
            "total_s": sent.get("seconds")}


def record(conn, row: dict, at: float, machine_id) -> int:
    direct = _direct_row(row, at) if "_direct" in row else None
    full = {**row, "at": at, "machine_id": machine_id}
    cur = conn.execute(f"INSERT INTO lane_probes ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                       tuple(full.get(c) for c in COLUMNS))
    conn.commit()
    if direct is not None:
        from harness import usage
        usage.insert(conn, [(direct, None)])
    return cur.lastrowid


def wake(conn, now: float, lanes=None, sender: Sender | None = None, machine_id=None, day=None, **kw) -> list[dict]:
    """Probe each text lane once at the same `now`, all in parallel, and record every row."""
    from harness import gateway, paths
    sender = sender or Sender(paths.home() / "watchdog")
    rows, out, slow = [], [], []
    for lane in lanes or gateway.TEXT_LANES:
        row, req = prepare(lane, sender, load=due(conn, lane, machine_id, now, day=day), **kw)
        handle = sender.start(lane, req["url"], req["headers"], req["body"], HOLD_S) if req else None
        rows.append((row, req, handle, time.monotonic() + timeout(lane)))
    for row, req, handle, deadline in rows:
        if handle is not None:
            sent = sender.collect(handle, deadline - time.monotonic())
            row = finish(row, sent, timeout(row["lane"]), req.get("node"))
            slow += [row["lane"]] if sent is None else []
            if sent is not None and not sent.get("failed") and not req["gateway"]:
                row["_direct"] = sent
        row["id"] = record(conn, row, now, machine_id) if conn is not None else None
        out.append(row)
    _cuts(out, slow)
    return out


def _cuts(rows: list[dict], slow: list[str]) -> None:
    """One cut per wake for the lanes the wait ran out on, one for replies that used the whole token allowance."""
    from harness import cuts
    if slow:
        cuts.cut("lane_probe_timeout", f"probes of {', '.join(slow)} read as slow",
                 value=max(timeout(lane) for lane in slow), kept=len(rows) - len(slow), dropped=len(slow))
    full = [r["lane"] for r in rows if (r.get("completion_tokens") or 0) >= max_tokens(r["lane"])]
    if full:
        cuts.cut("lane_probe_max_tokens", f"probe replies of {', '.join(full)} at their token allowance",
                 value=max(max_tokens(lane) for lane in full), kept=len(rows) - len(full), dropped=len(full))


def line(row: dict) -> str:
    what = row.get("reason") if row["outcome"] in (SKIPPED, SLOW, UP) else row.get("error")
    took = f" in {row['seconds']:.2f}s" if row.get("seconds") is not None and row["outcome"] == UP else ""
    return f"lane {row['lane']}: {row['outcome']}{took}" + (f" ({what})" if what else "")


if __name__ == "__main__" and sys.argv[1:] == ["send"]:
    raise SystemExit(child())
