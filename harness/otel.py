"""Claude Code's OpenTelemetry export, received over OTLP/HTTP JSON and stored per session and tool. #868."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from collections import defaultdict
from http.server import BaseHTTPRequestHandler

from harness.loopback import ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 4318
LOOPBACK = ("127.0.0.1", "localhost")
PREFIX = "claude_code."
#: Content attributes never stored: prompts, responses, tool arguments, error text, raw bodies, identity.
CONTENT = frozenset({"prompt", "prompt_text", "response", "tool_input", "tool_parameters", "error",
                     "body", "body_ref", "user.email", "workspace.host_paths"})
#: 1 delta, 2 cumulative, as OTLP numbers or enum names.
_TEMPORALITY = {1: "delta", 2: "cumulative", "AGGREGATION_TEMPORALITY_DELTA": "delta",
                "AGGREGATION_TEMPORALITY_CUMULATIVE": "cumulative"}


def env(host: str = HOST, port: int = PORT) -> dict:
    """The ~/.claude/settings.json `env` entries that send Claude Code's export here."""
    return {
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/json",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{host}:{port}",
        "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "delta",
        "OTEL_LOG_TOOL_DETAILS": "1",
    }


# --- OTLP JSON -> rows -----------------------------------------------------------------------------

def value(v):
    """One OTLP AnyValue as a Python value."""
    if not isinstance(v, dict):
        return v
    if "stringValue" in v:
        return v["stringValue"]
    if "intValue" in v:
        return int(v["intValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "boolValue" in v:
        return bool(v["boolValue"])
    if "arrayValue" in v:
        return [value(x) for x in (v["arrayValue"] or {}).get("values") or []]
    if "kvlistValue" in v:
        return attrs((v["kvlistValue"] or {}).get("values"))
    return None


def attrs(kvs) -> dict:
    return {kv.get("key"): value(kv.get("value")) for kv in kvs or [] if isinstance(kv, dict) and kv.get("key")}


def _secs(nanos) -> float | None:
    try:
        n = int(nanos)
    except (TypeError, ValueError):
        return None
    return n / 1e9 if n else None


def _iso(stamp) -> float | None:
    from harness.context_report import _epoch
    return _epoch(stamp) if stamp else None


def _num(v) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _params(a: dict) -> dict:
    raw = a.get("tool_parameters")
    if isinstance(raw, dict):
        return raw
    try:
        got = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def tool_of(a: dict) -> str:
    """The tool a row is about, named as `soh context` names it; '' when none."""
    from harness.context_report import display_name
    p = _params(a)
    server = a.get("mcp_server.name") or p.get("mcp_server_name")
    tool = a.get("mcp_tool.name") or p.get("mcp_tool_name")
    if server and tool:
        return f"{server} {tool}"
    return display_name(str(a.get("tool_name") or ""))


def _kept(a: dict) -> str:
    return json.dumps({k: v for k, v in a.items() if k not in CONTENT}, sort_keys=True, default=str)


def parse_metrics(doc: dict, received_at: float) -> list[dict]:
    """ExportMetricsServiceRequest JSON as one row per data point."""
    rows = []
    for rm in (doc or {}).get("resourceMetrics") or []:
        res = attrs((rm.get("resource") or {}).get("attributes"))
        for sm in rm.get("scopeMetrics") or []:
            for m in sm.get("metrics") or []:
                name = str(m.get("name") or "")
                kind = next((k for k in ("sum", "gauge", "histogram") if k in m), "")
                body = m.get(kind) or {}
                temporality = _TEMPORALITY.get(body.get("aggregationTemporality"), "")
                for dp in body.get("dataPoints") or []:
                    a = {**res, **attrs(dp.get("attributes"))}
                    v = _num(dp.get("asDouble", dp.get("asInt", dp.get("sum"))))
                    if v is None:
                        continue
                    at = _secs(dp.get("timeUnixNano")) or received_at
                    series = _key(name, {k: x for k, x in a.items() if k not in CONTENT})
                    rows.append({
                        "key": _key(series, dp.get("startTimeUnixNano"), dp.get("timeUnixNano"), v),
                        "series": series, "received_at": received_at, "at": at,
                        "session_id": str(a.get("session.id") or ""),
                        "name": name[len(PREFIX):] if name.startswith(PREFIX) else name,
                        "unit": str(m.get("unit") or ""), "temporality": temporality, "value": v,
                        "type": str(a.get("type") or ""), "model": str(a.get("model") or ""),
                        "query_source": str(a.get("query_source") or ""), "tool": tool_of(a),
                        "attrs": _kept(a)})
    return rows


def event_name(rec: dict, a: dict) -> str:
    name = a.get("event.name") or rec.get("eventName") or value(rec.get("body")) or ""
    name = str(name)
    return name[len(PREFIX):] if name.startswith(PREFIX) else name


def parse_logs(doc: dict, received_at: float) -> list[dict]:
    """ExportLogsServiceRequest JSON as one row per Claude Code event."""
    rows = []
    for rl in (doc or {}).get("resourceLogs") or []:
        res = attrs((rl.get("resource") or {}).get("attributes"))
        for sl in rl.get("scopeLogs") or []:
            for rec in sl.get("logRecords") or []:
                a = {**res, **attrs(rec.get("attributes"))}
                name = event_name(rec, a)
                if not name:
                    continue
                at = (_iso(a.get("event.timestamp")) or _secs(rec.get("timeUnixNano"))
                      or _secs(rec.get("observedTimeUnixNano")) or received_at)
                session = str(a.get("session.id") or "")
                ident = a.get("tool_use_id") or a.get("request_id") or a.get("client_request_id")
                key = _key(name, ident) if ident else _key(name, session, at, a.get("event.sequence"))
                success = a.get("success")
                rows.append({
                    "key": key, "received_at": received_at, "at": at, "session_id": session,
                    "prompt_id": str(a.get("prompt.id") or ""), "name": name, "tool": tool_of(a),
                    "model": str(a.get("model") or ""), "query_source": str(a.get("query_source") or ""),
                    "success": None if success is None else int(str(success).lower() == "true"),
                    "duration_ms": _num(a.get("duration_ms")),
                    "input_tokens": _num(a.get("input_tokens")),
                    "output_tokens": _num(a.get("output_tokens")),
                    "cache_read_tokens": _num(a.get("cache_read_tokens")),
                    "cache_creation_tokens": _num(a.get("cache_creation_tokens")),
                    "cache_creation_5m_tokens": _num(a.get("cache_creation_5m_tokens")),
                    "cache_creation_1h_tokens": _num(a.get("cache_creation_1h_tokens")),
                    "cost_usd": _num(a.get("cost_usd")),
                    "result_bytes": _num(a.get("tool_result_size_bytes")),
                    "attrs": _kept(a)})
    return rows


# --- the store -------------------------------------------------------------------------------------

_METRIC_COLS = ("key", "series", "received_at", "at", "session_id", "name", "unit", "temporality", "value",
                "type", "model", "query_source", "tool", "attrs")
_EVENT_COLS = ("key", "received_at", "at", "session_id", "prompt_id", "name", "tool", "model", "query_source",
               "success", "duration_ms", "input_tokens", "output_tokens", "cache_read_tokens",
               "cache_creation_tokens", "cache_creation_5m_tokens", "cache_creation_1h_tokens", "cost_usd",
               "result_bytes", "attrs")


def _insert(conn, table: str, cols: tuple, rows: list[dict]) -> int:
    sql = (f"INSERT OR IGNORE INTO {table} ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)})")
    n = 0
    for r in rows:
        cur = conn.execute(sql, tuple(r[c] for c in cols))
        n += max(getattr(cur, "rowcount", 0) or 0, 0)
    return n


def store(conn, metrics: list[dict] = (), events: list[dict] = ()) -> dict:
    """Insert rows once each: a retried export carries the same keys and adds nothing."""
    got = {"metrics": _insert(conn, "otel_metrics", _METRIC_COLS, list(metrics)),
           "events": _insert(conn, "otel_events", _EVENT_COLS, list(events))}
    conn.commit()
    return got


def _select(conn, table: str, since: float, until: float, name: str = "") -> list[dict]:
    sql = f"SELECT * FROM {table} WHERE at >= ? AND at < ?" + (" AND name = ?" if name else "") + " ORDER BY at"
    try:
        rows = conn.execute(sql, (since, until, name) if name else (since, until)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def events(conn, since: float, until: float, name: str = "") -> list[dict]:
    return _select(conn, "otel_events", since, until, name)


def metrics(conn, since: float, until: float, name: str = "") -> list[dict]:
    return _select(conn, "otel_metrics", since, until, name)


# --- the receiver ----------------------------------------------------------------------------------

_PARSERS = {"/v1/metrics": ("metrics", parse_metrics), "/v1/logs": ("events", parse_logs)}


def handle(path: str, ctype: str, encoding: str, raw: bytes, sink, now: float) -> tuple[int, dict]:
    """(status, JSON body) for one OTLP/HTTP export; `sink(metrics=, events=)` stores the rows."""
    route = path.split("?", 1)[0].rstrip("/")
    if route == "/v1/traces":
        return 200, {}
    if route not in _PARSERS:
        return 404, {"error": f"no OTLP signal at {route}"}
    if "json" not in (ctype or "").lower():
        return 415, {"error": "only http/json is received here; set OTEL_EXPORTER_OTLP_PROTOCOL=http/json"}
    try:
        if (encoding or "").lower() == "gzip":
            raw = gzip.decompress(raw)
        doc = json.loads(raw or b"{}")
    except (OSError, ValueError) as exc:
        return 400, {"error": f"unreadable export: {exc}"}
    kind, parse = _PARSERS[route]
    rows = parse(doc if isinstance(doc, dict) else {}, now)
    sink(**{kind: rows})
    return 200, {}


def _store_sink(**rows) -> None:
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        store(conn, **rows)
    finally:
        conn.close()


def server(host: str = HOST, port: int = PORT, sink=None, clock=None) -> ThreadingHTTPServer:
    """An OTLP/HTTP receiver bound to loopback; any other address is refused."""
    import time
    if host not in LOOPBACK:
        raise ValueError(f"the OTLP receiver binds loopback only ({', '.join(LOOPBACK)}), not {host!r}")
    sink = sink or _store_sink
    clock = clock or time.time

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            status, body = handle(self.path, self.headers.get("Content-Type", ""),
                                  self.headers.get("Content-Encoding", ""), self.rfile.read(n), sink, clock())
            out = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, fmt, *args):
            return None

    return ThreadingHTTPServer((host, port), Handler)


# --- reading: per day, per tool, and the comparison ------------------------------------------------

_TOKEN_TYPES = {"input": "input", "output": "output", "cacheRead": "cache_read", "cacheCreation": "cache_write"}


def metric_total(rows: list[dict], name: str, key=lambda r: "") -> dict:
    """Sum of a metric by key: deltas add, a cumulative series counts its largest reading."""
    out: dict = defaultdict(float)
    peak: dict = {}
    for r in rows:
        if r["name"] != name:
            continue
        if r["temporality"] == "cumulative":
            k = (key(r), r["series"])
            peak[k] = max(peak.get(k, 0.0), r["value"])
        else:
            out[key(r)] += r["value"]
    for (k, _), v in peak.items():
        out[k] += v
    return dict(out)


def from_events(ev: list[dict]) -> dict:
    api = [e for e in ev if e["name"] == "api_request"]
    tools = [e for e in ev if e["name"] == "tool_result"]
    s = lambda rows, c: sum(r[c] or 0 for r in rows)  # noqa: E731
    models: dict = defaultdict(int)
    for e in api:
        models[e["model"] or "?"] += sum(int(e[c] or 0) for c in _EVENT_TOKENS)
    return {"input": int(s(api, "input_tokens")),
            "output": int(s(api, "output_tokens")), "cache_read": int(s(api, "cache_read_tokens")),
            "cache_write": int(s(api, "cache_creation_tokens")),
            "cache_write_5m": int(s(api, "cache_creation_5m_tokens")),
            "cache_write_1h": int(s(api, "cache_creation_1h_tokens")), "requests": len(api),
            "tool_results": len(tools), "tool_tokens": sum(int(t["result_bytes"] or 0) // 4 for t in tools),
            "sessions": len({e["session_id"] for e in ev if e["session_id"]}),
            "models": dict(sorted(models.items()))}


#: api_request token fields summed per model; cost_usd is never read (#976).
_EVENT_TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")


def from_metrics(mt: list[dict]) -> dict:
    tok = metric_total(mt, "token.usage", key=lambda r: _TOKEN_TYPES.get(r["type"], r["type"]))
    models = metric_total(mt, "token.usage", key=lambda r: r["model"] or "?")
    unknown = {k: int(v) for k, v in sorted(tok.items()) if k not in _TOKEN_TYPES.values()}
    return {**{k: int(tok.get(k, 0)) for k in _TOKEN_TYPES.values()},
            "unknown_types": unknown, "models": {k: int(v) for k, v in sorted(models.items())}}


def from_ccusage(day: dict | None) -> dict | None:
    if day is None:
        return None
    t = day.get("tokens") or {}
    return {**{k: int(t.get(k) or 0) for k in _TOKEN_TYPES.values()},
            "models": {k: sum(int(n or 0) for n in v.values()) for k, v in sorted((day.get("models") or {}).items())}}


def from_transcripts(rows: list[dict], usage: dict | None = None) -> dict:
    return {**(usage or {}), "tool_results": len(rows), "tool_tokens": sum(r["tokens"] for r in rows)}


#: (row, label) in the comparison table, and which sources measure each.
COMPARE_ROWS = (("input", "input tokens"), ("output", "output tokens"),
                ("cache_read", "cache read tokens"), ("cache_write", "cache write tokens"),
                ("cache_write_5m", "  of which 5m"), ("cache_write_1h", "  of which 1h"),
                ("requests", "API requests"), ("tool_results", "tool results"),
                ("tool_tokens", "tool result tokens (est)"), ("sessions", "sessions"))
SOURCES = ("otel_events", "otel_metrics", "ccusage", "transcripts", "ledger")


def compare(day: str, ev: list[dict], mt: list[dict], cc_day: dict | None, ctx_rows: list[dict],
            ccusage_available: bool = True, usage: dict | None = None, chosen: dict | None = None) -> dict:
    """One day side by side: OTel events, OTel metrics, ccusage, transcripts, and what the ledger counts (#1160)."""
    cols = {"otel_events": from_events(ev) if ev else None,
            "otel_metrics": from_metrics(mt) if mt else None,
            "ccusage": from_ccusage(cc_day) if ccusage_available else None,
            "transcripts": from_transcripts(ctx_rows, usage),
            "ledger": (chosen or {}).get("tokens")}
    rows = []
    for k, label in COMPARE_ROWS:
        rows.append({"row": k, "label": label,
                     **{s: (cols[s] or {}).get(k) if cols[s] is not None else None for s in SOURCES}})
    models = sorted({m for s in ("otel_events", "otel_metrics", "ccusage") for m in ((cols[s] or {}).get("models") or {})})
    by_model = [{"model": m, **{s: ((cols[s] or {}).get("models") or {}).get(m)
                                for s in ("otel_events", "otel_metrics", "ccusage")}} for m in models]
    return {"day": day, "sources": {s: cols[s] is not None for s in SOURCES}, "rows": rows, "models": by_model,
            "notes": {"tool_tokens": "OTel: tool_result_size_bytes / 4; transcripts: characters / 4",
                      "otel_metrics": "delta points summed; a cumulative series counts its largest reading"}}


# --- tool categories for `soh context --by category` ----------------------------------------------

CATEGORIES = ("read", "search", "shell", "edit", "web", "agent", "memory", "media", "other")
_BUILTIN = {"Read": "read", "NotebookRead": "read", "Grep": "search", "Glob": "search", "LS": "search",
            "ToolSearch": "search", "Bash": "shell", "BashOutput": "shell", "KillShell": "shell",
            "PowerShell": "shell", "Monitor": "shell", "Edit": "edit", "Write": "edit", "MultiEdit": "edit",
            "NotebookEdit": "edit", "WebFetch": "web", "WebSearch": "web", "Agent": "agent", "Task": "agent",
            "SendMessage": "agent"}


def category(tool: str) -> str:
    """The deterministic category; 'other' for a tool the table does not name."""
    return _BUILTIN.get(tool, "other")


def categorize(tools, label=None) -> dict[str, str]:
    """tool -> category; `label(tool)` is asked only for tools the table leaves 'other', and any failure keeps 'other'."""
    out = {}
    for t in sorted(set(tools)):
        c = category(t)
        if c == "other" and label is not None:
            try:
                got = label(t)
            except Exception:  # noqa: BLE001
                got = None
            c = got if got in CATEGORIES else c
        out[t] = c
    return out


def local_label(tool: str) -> str | None:
    """The decide lane's category for one tool name; None when it cannot answer."""
    from harness import delegate
    schema = {"category": {"type": "enum", "choices": list(CATEGORIES),
                           "description": "what the tool mostly does with its result"}}
    got = delegate.decide(f"Which category fits the Claude Code tool named {tool!r}? "
                          "memory means a knowledge base or notes store; media means images, audio or video.",
                          schema)
    return (got.get("answers") or {}).get("category")
