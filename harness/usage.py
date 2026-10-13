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

from harness import paths, purpose

#: Characters of prompt or completion kept per sample when text is on.
SAMPLE_CHARS = 8000
#: Newest samples kept when text is on; older ones are deleted.
SAMPLE_ROWS = 2000
#: The meta key that turns text samples on; absent is off.
TEXT_KEY = "usage_text"
QUEUE_MAX = 10000
BATCH_MAX = 500
#: The meta key holding [at, rows] for each flush that dropped rows, so a report knows its sample is short. #700.
DROPS_KEY = "usage_dropped"
#: Seconds of drop history kept, longer than any window a report reads.
DROP_HISTORY = 90 * 86400.0
FLUSH_S = 1.0
LANE_PREFIX = "sohot-"

COLUMNS = ("at", "alias", "lane", "served", "spec", "client", "call_type", "stream",
           "prompt_tokens", "completion_tokens", "ttft_s", "total_s", "tool_calls",
           "tool_calls_valid", "finish_reason", "error_class", "error_code", "purpose")


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
        "purpose": purpose.of_tags(slo.get("request_tags")),
    }


#: The client a delegated request that bypassed the gateway is recorded under. #825.
DIRECT_CLIENT = "soh-delegate"


def direct_row(lane: str, spec: str, served: str, at: float, got: dict | None = None,
               error: BaseException | None = None, stream: bool = False) -> dict:
    """A delegated request that went straight to an engine, as the row the gateway would have written. #825."""
    from harness import gateway
    got = got or {}
    alias = gateway.LANE_ALIAS.format(lane)
    return {"at": at, "alias": alias, "lane": lane, "served": served or "", "spec": spec or alias,
            "client": DIRECT_CLIENT, "call_type": "acompletion", "stream": int(stream),
            "prompt_tokens": _num(got.get("prompt_tokens"), int),
            "completion_tokens": _num(got.get("completion_tokens"), int),
            "ttft_s": _num(got.get("ttft_s")) if stream else None,
            "total_s": _num(got.get("seconds")) if error is None else time.time() - at,
            "tool_calls": 0, "tool_calls_valid": 0, "finish_reason": "",
            "error_class": type(error).__name__ if error is not None else "",
            "error_code": str(getattr(error, "failure_class", "") or "") if error is not None else "",
            "purpose": purpose.WORK}


def record(r: dict, connect=None) -> bool:
    """Write one row now, never raising; False when the store is not this checkout's to write."""
    try:
        if connect is None:
            from harness import memory_store as ms
            path = target()
            if path is None:
                return False
            conn = ms.connect(path)
        else:
            conn = connect()
        try:
            insert(conn, [(r, None)])
        finally:
            conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


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
        cur = conn.execute(sql, {**{c: r.get(c) for c in COLUMNS},
                                 "purpose": r.get("purpose") or purpose.UNKNOWN})
        if keep and s:
            conn.execute("INSERT INTO gateway_samples (request_id, prompt, completion) "
                         "VALUES (?, ?, ?)", (cur.lastrowid, s.get("prompt", ""),
                                              s.get("completion", "")))
    if keep:
        conn.execute("DELETE FROM gateway_samples WHERE request_id NOT IN (SELECT "
                     "request_id FROM gateway_samples ORDER BY request_id DESC LIMIT ?)",
                     (SAMPLE_ROWS,))
    conn.commit()


def record_dropped(conn, rows: int, at: float | None = None) -> None:
    """Note that `rows` usage rows were lost at `at`, keeping DROP_HISTORY of such notes."""
    at = time.time() if at is None else float(at)
    kept = [d for d in _drops(conn) if d[0] >= at - DROP_HISTORY] + [[at, int(rows)]]
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (DROPS_KEY, json.dumps(kept)))
    conn.commit()


def _drops(conn) -> list:
    got = conn.execute("SELECT value FROM meta WHERE key = ?", (DROPS_KEY,)).fetchone()
    try:
        return [list(d) for d in json.loads(got[0])] if got else []
    except (TypeError, ValueError):
        return []


def dropped_since(conn, start: float) -> int:
    """Usage rows the writer lost at or after `start`."""
    return sum(int(n) for at, n in _drops(conn) if at >= start)


def drop_warning(conn, start: float) -> list[str]:
    """A line saying the window's rows are incomplete, or none."""
    n = dropped_since(conn, start)
    return [f"{n} gateway usage row(s) were dropped in this window; its rates are on an incomplete sample"] if n else []


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
        self._unsaved = 0
        self._lock = threading.Lock()
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
            self._drop(1, "the queue is full")

    def _drop(self, n: int, why: str) -> None:
        with self._lock:
            first = self.dropped == 0
            self.dropped += n
            self._unsaved += n
        if first:
            self._log(f"dropping usage rows: {why}")

    def _save_drops(self, conn) -> None:
        with self._lock:
            n, self._unsaved = self._unsaved, 0
        if n:
            try:
                record_dropped(conn, n)
            except Exception:  # noqa: BLE001
                with self._lock:
                    self._unsaved += n

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
                    if self._unsaved and not self.disabled:
                        try:
                            conn = conn or self._open()
                            self._save_drops(conn)
                        except Exception as exc:  # noqa: BLE001
                            self._log(f"{self._unsaved} dropped row(s) not recorded: {exc}")
                    break
                continue
            if self.disabled:
                with self._lock:
                    self.dropped += len(batch)
                continue
            try:
                if conn is None:
                    conn = self._open()
                    self.specs = _specs(conn)
                insert(conn, [({**r, "spec": self.specs.get(r.get("alias")) or r.get("spec")}, s)
                              for r, s in batch])
                self._save_drops(conn)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.dropped += len(batch)
                    self._unsaved += len(batch)
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
#: How many cluster-robust standard errors a rate must rise by to be called a regression.
Z_WARN = 3.0
#: A client's requests further apart than this are separate sessions; one session is one piece of evidence. #701.
SESSION_GAP_S = 300.0
#: Failures the gateway or the client caused, which say nothing about the model behind the alias. #701.
NOT_MODEL_ERRORS = frozenset({"AuthenticationError", "PermissionDeniedError", "RateLimitError",
                              "NotFoundError", "BadRequestError", "BudgetExceededError",
                              "UnprocessableEntityError"})
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
    """Requests, tokens, TTFT p50/p95, model error rate, gateway errors apart, and invalid tool-call rate of some rows."""
    n = len(rows)
    gateway = sum(1 for r in rows if r["error_class"] in NOT_MODEL_ERRORS)
    errors = sum(1 for r in rows if r["error_class"]) - gateway
    calls = sum(r["tool_calls"] or 0 for r in rows)
    invalid = calls - sum(r["tool_calls_valid"] or 0 for r in rows)
    ttft = [r["ttft_s"] for r in rows if r["ttft_s"] is not None and not r["error_class"]]
    return {"requests": n, "errors": errors,
            "error_rate": errors / n if n else None,
            "gateway_errors": gateway, "gateway_error_rate": gateway / n if n else None,
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
    """stats() per (purpose, alias, served model) over the window, busiest first."""
    now = time.time() if now is None else now
    since = parse_since(DEFAULT_SINCE) if since is None else since
    groups: dict = {}
    for r in _rows(conn, lane, now - since):
        groups.setdefault((_purpose(r), r["alias"], r["served"]), []).append(r)
    out = [{"purpose": p, "alias": a, "served": m, "lane": lane_of(a),
            "spec": rows[-1]["spec"], **stats(rows)} for (p, a, m), rows in groups.items()]
    return sorted(out, key=lambda s: (-s["requests"], s["purpose"], s["alias"], s["served"]))


def _purpose(r: dict) -> str:
    return r.get("purpose") or purpose.UNKNOWN


def by_purpose(conn, lane=None, since=None, now=None) -> list[dict]:
    """stats() per purpose over the window, busiest first. #825."""
    now = time.time() if now is None else now
    since = parse_since(DEFAULT_SINCE) if since is None else since
    groups: dict = {}
    for r in _rows(conn, lane, now - since):
        groups.setdefault(_purpose(r), []).append(r)
    out = [{"purpose": p, **stats(rows)} for p, rows in groups.items()]
    return sorted(out, key=lambda s: (-s["requests"], s["purpose"]))


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
            before, after = _rows(conn, name, start, at), _rows(conn, name, at, nxt)
            out.append({"switch": sw, "before": stats(before), "after": stats(after),
                        "sessions": {"before": sessions(before), "after": sessions(after)}})
    return sorted(out, key=lambda c: c["switch"]["switched_at"])


def sessions(rows: list[dict]) -> list[list[int]]:
    """[requests, model errors, tool calls, invalid calls] per client session, in client then time order.

    One session cannot estimate its own variance, so a single one is cut into SESSION_GAP_S blocks. #701.
    """
    one = _clusters(rows) == 1
    out: list[list[int]] = []
    last: tuple | None = None
    start = 0.0
    for r in sorted(rows, key=lambda r: (r["client"] or "", r["at"])):
        client = r["client"] or ""
        if (last is None or last[0] != client or r["at"] - last[1] > SESSION_GAP_S
                or (one and r["at"] - start >= SESSION_GAP_S)):
            out.append([0, 0, 0, 0])
            start = r["at"]
        last = (client, r["at"])
        calls = r["tool_calls"] or 0
        cls = r["error_class"] or ""
        out[-1][0] += 1
        out[-1][1] += int(bool(cls) and cls not in NOT_MODEL_ERRORS)
        out[-1][2] += calls
        out[-1][3] += calls - (r["tool_calls_valid"] or 0)
    return out


def _clusters(rows: list[dict]) -> int:
    """How many client sessions the rows make."""
    n, last = 0, None
    for r in sorted(rows, key=lambda r: (r["client"] or "", r["at"])):
        client = r["client"] or ""
        if last is None or last[0] != client or r["at"] - last[1] > SESSION_GAP_S:
            n += 1
        last = (client, r["at"])
    return n


def _rate_var(clusters: list[tuple[int, int]]) -> tuple[float, float, int]:
    """(rate, cluster-robust variance of the rate, trials) over (hits, trials) clusters."""
    used = [(k, n) for k, n in clusters if n]
    total = sum(n for _, n in used)
    if not total:
        return 0.0, 0.0, 0
    p = sum(k for k, _ in used) / total
    g = len(used)
    if g < 2:
        return p, float("inf"), total
    return p, g / (g - 1) * sum((k - p * n) ** 2 for k, n in used) / total ** 2, total


def _worse(before: list[tuple[int, int]], after: list[tuple[int, int]]) -> tuple[float, float] | None:
    """(before rate, after rate) when after is above before by more than Z_WARN clustered standard errors, else None."""
    p1, v1, n1 = _rate_var(before)
    p2, v2, n2 = _rate_var(after)
    if n1 < MIN_REQUESTS or n2 < MIN_REQUESTS or p2 <= p1:
        return None
    se = (v1 + v2) ** 0.5
    return (p1, p2) if se == 0 or (p2 - p1) / se > Z_WARN else None


def regressions(comparisons: list[dict]) -> list[str]:
    """A warning per switch after which model errors or invalid tool calls rose beyond session-clustered noise."""
    out = []
    for c in comparisons:
        sw, b, a = c["switch"], c["sessions"]["before"], c["sessions"]["after"]
        named = (f"sohot-{sw['lane']} after switch #{sw['id']} "
                 f"({sw['old_spec']} -> {sw['new_spec']}, "
                 f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(sw['switched_at']))})")
        got = _worse([(s[1], s[0]) for s in b], [(s[1], s[0]) for s in a])
        if got:
            out.append(f"{named}: error rate {got[0]:.1%} -> {got[1]:.1%} "
                       f"over {c['before']['requests']} / {c['after']['requests']} requests "
                       f"in {len(b)} / {len(a)} sessions")
        got = _worse([(s[3], s[2]) for s in b], [(s[3], s[2]) for s in a])
        if got:
            out.append(f"{named}: invalid tool-call rate {got[0]:.1%} -> {got[1]:.1%} "
                       f"over {c['before']['tool_calls']} / {c['after']['tool_calls']} calls")
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
