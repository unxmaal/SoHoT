"""Real use through the gateway, one row per request, no text unless asked. #481.

gateway/usage_log.py hands each LiteLLM success or failure to a Writer, which
queues it and writes batches from its own thread, so serving never waits on the
store and a store failure never fails a request.
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time

from harness import paths

#: Characters of prompt or completion kept per sample when text is on.
SAMPLE_CHARS = 8000
#: Newest samples kept when text is on; older ones are deleted.
SAMPLE_ROWS = 2000
#: The meta key that turns text samples on; absent is off.
TEXT_KEY = "usage_text"
QUEUE_MAX = 10000
BATCH_MAX = 500
FLUSH_S = 1.0
LANE_PREFIX = "sohot-"

COLUMNS = ("at", "alias", "lane", "served", "spec", "client", "call_type", "stream",
           "prompt_tokens", "completion_tokens", "ttft_s", "total_s", "tool_calls",
           "tool_calls_valid", "finish_reason", "error_class", "error_code")


def _plain(obj):
    """A ModelResponse as a dict; a dict as itself; anything else as {}."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            got = dump()
        except Exception:  # noqa: BLE001
            return {}
        return got if isinstance(got, dict) else {}
    return {}


def _num(x, kind=float):
    try:
        return kind(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _offered(kwargs: dict) -> set[str]:
    """Tool names the request offered, OpenAI or Anthropic shape."""
    tools = (kwargs.get("optional_params") or {}).get("tools") or kwargs.get("tools") or []
    names = set()
    for t in tools if isinstance(tools, list) else []:
        if isinstance(t, dict):
            fn = t.get("function") if isinstance(t.get("function"), dict) else t
            if fn.get("name"):
                names.add(str(fn["name"]))
    return names


def _message(resp: dict) -> tuple[dict, str]:
    choices = resp.get("choices") or []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    return (first.get("message") or {}), str(first.get("finish_reason") or "")


def _calls(message: dict, offered: set[str]) -> tuple[int, int]:
    """(tool calls, those that parse to an object and name an offered tool)."""
    calls = message.get("tool_calls") or []
    valid = 0
    for c in calls:
        fn = (c or {}).get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "")
        except (TypeError, ValueError):
            continue
        if isinstance(args, dict) and fn.get("name") in offered:
            valid += 1
    return len(calls), valid


def client_of(slo: dict) -> str:
    """The key alias when the key has one, else the user agent's first product token."""
    meta = slo.get("metadata") or {}
    if meta.get("user_api_key_alias"):
        return str(meta["user_api_key_alias"])[:64]
    ua = str(slo.get("user_agent") or meta.get("user_agent") or "").strip()
    return ua.split()[0][:64] if ua else ""


def lane_of(alias: str) -> str:
    return alias[len(LANE_PREFIX):] if alias.startswith(LANE_PREFIX) else ""


def row(kwargs, response_obj, specs: dict | None = None) -> dict:
    """One request as a gateway_requests row. Never raises; carries no text."""
    kwargs = kwargs if isinstance(kwargs, dict) else {}
    slo = kwargs.get("standard_logging_object") or {}
    slo = slo if isinstance(slo, dict) else {}
    alias = str(slo.get("model_group") or "")
    start, end = _num(slo.get("startTime")), _num(slo.get("endTime"))
    first = _num(slo.get("completionStartTime"))
    stream = bool(slo.get("stream") or kwargs.get("stream") is True)
    err = slo.get("error_information") or {}
    failed = slo.get("status") == "failure"
    message, finish = _message(_plain(response_obj))
    calls, valid = _calls(message, _offered(kwargs))
    return {
        "at": start if start is not None else time.time(),
        "alias": alias, "lane": lane_of(alias),
        "served": str(slo.get("model") or ""),
        "spec": (specs or {}).get(alias) or alias,
        "client": client_of(slo),
        "call_type": str(slo.get("call_type") or kwargs.get("call_type") or ""),
        "stream": int(stream),
        "prompt_tokens": _num(slo.get("prompt_tokens"), int),
        "completion_tokens": _num(slo.get("completion_tokens"), int),
        "ttft_s": (first - start if stream and first is not None and start is not None
                   else None),
        "total_s": end - start if end is not None and start is not None else None,
        "tool_calls": calls, "tool_calls_valid": valid,
        "finish_reason": finish,
        "error_class": (str(err.get("error_class") or "") or "error") if failed else "",
        "error_code": str(err.get("error_code") or "") if failed else "",
    }


def sample(kwargs, response_obj) -> dict:
    """The prompt and completion text, each cut to SAMPLE_CHARS. Kept only when text is on."""
    kwargs = kwargs if isinstance(kwargs, dict) else {}
    slo = kwargs.get("standard_logging_object") or {}
    msgs = slo.get("messages") if isinstance(slo, dict) else None
    msgs = msgs if msgs is not None else kwargs.get("messages")
    message, _ = _message(_plain(response_obj))
    out = {"content": message.get("content"), "tool_calls": message.get("tool_calls")}
    return {"prompt": json.dumps(msgs, default=str)[:SAMPLE_CHARS],
            "completion": json.dumps(out, default=str)[:SAMPLE_CHARS]}


def text_enabled(conn) -> bool:
    got = conn.execute("SELECT value FROM meta WHERE key = ?", (TEXT_KEY,)).fetchone()
    return bool(got) and got[0] == "1"


def set_text(conn, on: bool) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (TEXT_KEY, "1" if on else "0"))
    conn.commit()


def target():
    """The store to write, or None: the live store only from the deploy checkout."""
    from harness import memory_store as ms
    path = ms.db_path()
    if paths.is_live(path) and paths.runs_elsewhere() is not None:
        return None
    return path


def _specs(conn) -> dict:
    """sohot-<lane> -> the spec it serves; the served config was written from the same table."""
    from harness import adopt, gateway
    try:
        got = adopt.lane_defaults(conn)
    except Exception:  # noqa: BLE001
        return {}
    return {gateway.LANE_ALIAS.format(lane): spec for lane, spec in got.items()}


def insert(conn, rows: list[tuple[dict, dict | None]]) -> None:
    """Write a batch; with text on, its samples too, keeping the newest SAMPLE_ROWS."""
    keep = text_enabled(conn)
    sql = (f"INSERT INTO gateway_requests ({', '.join(COLUMNS)}) VALUES "
           f"({', '.join(':' + c for c in COLUMNS)})")
    for r, s in rows:
        cur = conn.execute(sql, {c: r.get(c) for c in COLUMNS})
        if keep and s:
            conn.execute("INSERT INTO gateway_samples (request_id, prompt, completion) "
                         "VALUES (?, ?, ?)", (cur.lastrowid, s.get("prompt", ""),
                                              s.get("completion", "")))
    if keep:
        conn.execute("DELETE FROM gateway_samples WHERE request_id NOT IN (SELECT "
                     "request_id FROM gateway_samples ORDER BY request_id DESC LIMIT ?)",
                     (SAMPLE_ROWS,))
    conn.commit()


class Writer:
    """A queue and one thread that drains it into the store in batches."""

    def __init__(self, connect=None, flush_s: float = FLUSH_S, maxsize: int = QUEUE_MAX,
                 log=None):
        self._connect = connect
        self._flush_s = flush_s
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._log = log or (lambda m: print(f"usage_log: {m}", file=sys.stderr, flush=True))
        self._thread = None
        self._stop = threading.Event()
        self.dropped = 0
        self.disabled = ""
        self.specs: dict = {}

    def start(self) -> "Writer":
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="usage-writer",
                                            daemon=True)
            self._thread.start()
        return self

    def put(self, r: dict, s: dict | None = None) -> None:
        """Enqueue without waiting; a full queue drops the row and counts it."""
        try:
            self._q.put_nowait((r, s))
        except queue.Full:
            self.dropped += 1

    def _open(self):
        if self._connect is not None:
            return self._connect()
        from harness import memory_store as ms
        path = target()
        if path is None:
            self.disabled = "the live store is written only by the deploy checkout's gateway"
            raise RuntimeError(self.disabled)
        return ms.connect(path)

    def _drain(self, block: bool) -> list:
        got = []
        try:
            got.append(self._q.get(timeout=self._flush_s) if block else self._q.get_nowait())
            while len(got) < BATCH_MAX:
                got.append(self._q.get_nowait())
        except queue.Empty:
            pass
        return got

    def _run(self) -> None:
        conn = None
        warned = False
        while True:
            stopping = self._stop.is_set()
            batch = self._drain(block=not stopping)
            if not batch:
                if stopping:
                    break
                continue
            if self.disabled:
                self.dropped += len(batch)
                continue
            try:
                if conn is None:
                    conn = self._open()
                    self.specs = _specs(conn)
                insert(conn, [({**r, "spec": self.specs.get(r.get("alias")) or r.get("spec")}, s)
                              for r, s in batch])
            except Exception as exc:  # noqa: BLE001
                self.dropped += len(batch)
                if not warned:
                    self._log(f"dropping usage rows: {exc}")
                    warned = True
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = None
        if conn is not None:
            conn.close()

    def close(self, timeout: float = 30.0) -> None:
        """Write what is queued, then stop."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)



# ---- what the rows say -------------------------------------------------------

#: Fewer requests (or tool calls) than this on either side of a switch says nothing.
MIN_REQUESTS = 20
#: How many standard errors a rate must rise by to be called a regression.
Z_WARN = 3.0
DEFAULT_SINCE = "7d"
_UNITS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}


def parse_since(text) -> float:
    """'7d', '12h', '30m', '90s' or a bare number of days, as seconds."""
    raw = str(text).strip().lower()
    unit = raw[-1:] if raw[-1:] in _UNITS else "d"
    try:
        return float(raw[:-1] if raw[-1:] in _UNITS else raw) * _UNITS[unit]
    except ValueError:
        raise ValueError(f"cannot read {text!r} as a window; use 7d, 12h, 30m or 90s") from None


def _pct(values: list[float], q: float):
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, max(0, round(q * (len(v) - 1))))]


def stats(rows: list[dict]) -> dict:
    """Requests, tokens, TTFT p50/p95, error rate and invalid tool-call rate of some rows."""
    n = len(rows)
    errors = sum(1 for r in rows if r["error_class"])
    calls = sum(r["tool_calls"] or 0 for r in rows)
    invalid = calls - sum(r["tool_calls_valid"] or 0 for r in rows)
    ttft = [r["ttft_s"] for r in rows if r["ttft_s"] is not None and not r["error_class"]]
    return {"requests": n, "errors": errors,
            "error_rate": errors / n if n else None,
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
            "ttft_p50": _pct(ttft, 0.5), "ttft_p95": _pct(ttft, 0.95),
            "tool_calls": calls, "invalid_calls": invalid,
            "invalid_rate": invalid / calls if calls else None}


def _rows(conn, lane=None, start=None, end=None) -> list[dict]:
    sql, args = "SELECT * FROM gateway_requests WHERE 1 = 1", []
    if lane:
        sql += " AND lane = ?"
        args.append(lane)
    if start is not None:
        sql += " AND at >= ?"
        args.append(start)
    if end is not None:
        sql += " AND at < ?"
        args.append(end)
    return [dict(r) for r in conn.execute(sql + " ORDER BY at", args).fetchall()]


def summary(conn, lane=None, since=None, now=None) -> list[dict]:
    """stats() per (alias, served model) over the window, busiest first."""
    now = time.time() if now is None else now
    since = parse_since(DEFAULT_SINCE) if since is None else since
    groups: dict = {}
    for r in _rows(conn, lane, now - since):
        groups.setdefault((r["alias"], r["served"]), []).append(r)
    out = [{"alias": a, "served": m, "lane": lane_of(a),
            "spec": rows[-1]["spec"], **stats(rows)} for (a, m), rows in groups.items()]
    return sorted(out, key=lambda s: (-s["requests"], s["alias"], s["served"]))


def around_switches(conn, lane=None, since=None, now=None) -> list[dict]:
    """Each alias switch in the window with stats() of its alias before and after it."""
    from harness import gateway_switch
    now = time.time() if now is None else now
    since = parse_since(DEFAULT_SINCE) if since is None else since
    by_lane: dict = {}
    for sw in gateway_switch.switches(conn):
        by_lane.setdefault(sw["lane"], []).append(sw)
    out = []
    for name, sws in by_lane.items():
        if lane and name != lane:
            continue
        for i, sw in enumerate(sws):
            at = sw["switched_at"]
            if at < now - since:
                continue
            prev = sws[i - 1]["switched_at"] if i else None
            nxt = sws[i + 1]["switched_at"] if i + 1 < len(sws) else None
            span = (nxt or now) - at
            start = max(prev if prev is not None else at - span, at - since)
            out.append({"switch": sw,
                        "before": stats(_rows(conn, name, start, at)),
                        "after": stats(_rows(conn, name, at, nxt))})
    return sorted(out, key=lambda c: c["switch"]["switched_at"])


def _worse(k1: int, n1: int, k2: int, n2: int) -> bool:
    """Is k2/n2 above k1/n1 by more than Z_WARN standard errors, with enough of each."""
    if n1 < MIN_REQUESTS or n2 < MIN_REQUESTS:
        return False
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = (pooled * (1 - pooled) * (1 / n1 + 1 / n2)) ** 0.5
    return p2 > p1 and (se == 0 or (p2 - p1) / se > Z_WARN)


def regressions(comparisons: list[dict]) -> list[str]:
    """A warning per switch after which errors or invalid tool calls rose beyond noise."""
    out = []
    for c in comparisons:
        sw, b, a = c["switch"], c["before"], c["after"]
        named = (f"sohot-{sw['lane']} after switch #{sw['id']} "
                 f"({sw['old_spec']} -> {sw['new_spec']}, "
                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(sw['switched_at']))})")
        if _worse(b["errors"], b["requests"], a["errors"], a["requests"]):
            out.append(f"{named}: error rate {b['error_rate']:.1%} -> {a['error_rate']:.1%} "
                       f"over {b['requests']} / {a['requests']} requests")
        if _worse(b["invalid_calls"], b["tool_calls"], a["invalid_calls"], a["tool_calls"]):
            out.append(f"{named}: invalid tool-call rate {b['invalid_rate']:.1%} -> "
                       f"{a['invalid_rate']:.1%} over {b['tool_calls']} / {a['tool_calls']} calls")
    return out


def real_use(conn, since=None, now=None) -> dict:
    """{lane: stats() of its sohot-<lane> alias} over the window, for the report pages."""
    now = time.time() if now is None else now
    since = parse_since(DEFAULT_SINCE) if since is None else since
    by: dict = {}
    for r in _rows(conn, None, now - since):
        if r["lane"]:
            by.setdefault(r["lane"], []).append(r)
    return {lane: stats(rows) for lane, rows in sorted(by.items())}
