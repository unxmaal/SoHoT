"""#825: every gateway request carries its purpose, and the usage log groups by it."""
import json
import re
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from harness import completion, context, delegate, gateway_key, purpose, serving, usage
from harness import memory_store as ms
from harness.loopback import ThreadingHTTPServer

REPO = Path(__file__).resolve().parents[1]


def slo_with(tags):
    return {"standard_logging_object": {"model_group": "sohot-code", "startTime": 1.0,
                                        "endTime": 2.0, "request_tags": tags}}


# ---- the tag becomes the column ------------------------------------------------


def test_the_purpose_tag_becomes_the_rows_purpose_beside_user_agent_tags():
    tags = ["purpose:eval", "User-Agent: python-httpx", "User-Agent: python-httpx/0.28.1"]
    assert usage.row(slo_with(tags), None)["purpose"] == "eval"


@pytest.mark.parametrize("tags", [None, [], ["User-Agent: curl"], ["purpose:bogus"], "purpose:eval"])
def test_no_known_purpose_tag_is_unknown(tags):
    assert usage.row(slo_with(tags), None)["purpose"] == "unknown"


def test_a_written_row_keeps_its_purpose():
    conn = ms.connect()
    try:
        usage.insert(conn, [(usage.row(slo_with(["purpose:smoke"]), None), None)])
        assert conn.execute("SELECT purpose FROM gateway_requests").fetchone()[0] == "smoke"
    finally:
        conn.close()


def test_a_row_written_without_purpose_is_unknown():
    conn = ms.connect()
    try:
        conn.execute("INSERT INTO gateway_requests (at) VALUES (1.0)")
        assert conn.execute("SELECT purpose FROM gateway_requests").fetchone()[0] == "unknown"
    finally:
        conn.close()


OLD_REQUESTS = """
CREATE TABLE gateway_requests (
    id INTEGER PRIMARY KEY, at REAL NOT NULL, alias TEXT NOT NULL DEFAULT '',
    lane TEXT NOT NULL DEFAULT '', served TEXT NOT NULL DEFAULT '',
    spec TEXT NOT NULL DEFAULT '', client TEXT NOT NULL DEFAULT '',
    call_type TEXT NOT NULL DEFAULT '', stream INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER, completion_tokens INTEGER, ttft_s REAL, total_s REAL,
    tool_calls INTEGER NOT NULL DEFAULT 0, tool_calls_valid INTEGER NOT NULL DEFAULT 0,
    finish_reason TEXT NOT NULL DEFAULT '', error_class TEXT NOT NULL DEFAULT '',
    error_code TEXT NOT NULL DEFAULT '');
"""


def test_a_schema_67_store_gains_the_column_and_its_rows_are_unknown(old_store):
    rows = ("INSERT INTO gateway_requests (at, client) VALUES (1.0, 'Python-urllib/3.12');"
            "INSERT INTO gateway_requests (at, client) VALUES (2.0, 'python-httpx/0.28.1');")
    path = old_store(67, rows, ddl=OLD_REQUESTS)
    conn = ms.connect(path)
    try:
        got = [tuple(r) for r in conn.execute(
            "SELECT client, purpose FROM gateway_requests ORDER BY at")]
        assert got == [("Python-urllib/3.12", "unknown"), ("python-httpx/0.28.1", "unknown")]
        assert conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(ms.SCHEMA_VERSION)
    finally:
        conn.close()


# ---- soh usage groups by purpose -------------------------------------------------


def _put(conn, purpose_, alias="sohot-code", n=1, at=1000.0, prompt=10):
    for i in range(n):
        r = usage.row(slo_with([f"purpose:{purpose_}"] if purpose_ else None), None)
        r.update(at=at + i, alias=alias, prompt_tokens=prompt)
        usage.insert(conn, [(r, None)])


def test_the_summary_splits_one_alias_by_purpose_and_totals_each_purpose():
    conn = ms.connect()
    try:
        _put(conn, "eval", n=3)
        _put(conn, "work", n=2)
        _put(conn, "work", alias="sohot-decide", n=1)
        _put(conn, "", n=1)
        got = {(s["purpose"], s["alias"]): s["requests"]
               for s in usage.summary(conn, since=1e9, now=2000.0)}
        assert got == {("eval", "sohot-code"): 3, ("work", "sohot-code"): 2,
                       ("work", "sohot-decide"): 1, ("unknown", "sohot-code"): 1}
        totals = usage.by_purpose(conn, since=1e9, now=2000.0)
        assert [(t["purpose"], t["requests"], t["prompt_tokens"]) for t in totals] == [
            ("eval", 3, 30), ("work", 3, 30), ("unknown", 1, 10)]
    finally:
        conn.close()


def test_soh_usage_prints_and_emits_the_purpose_totals(capsys):
    from harness import cli
    conn = ms.connect()
    try:
        _put(conn, "smoke", at=usage.time.time() - 60, n=2)
    finally:
        conn.close()
    assert cli.main(["usage", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [(p["purpose"], p["requests"]) for p in out["purposes"]] == [("smoke", 2)]
    assert out["summary"][0]["purpose"] == "smoke"


# ---- callers send their purpose --------------------------------------------------


def test_no_purpose_is_sent_until_one_is_set(monkeypatch):
    monkeypatch.delenv(purpose.ENV, raising=False)
    assert purpose.headers() == {}
    with purpose.using("work"):
        assert purpose.headers() == {"x-litellm-tags": "purpose:work"}
    monkeypatch.setenv(purpose.ENV, "eval")
    assert purpose.headers() == {"x-litellm-tags": "purpose:eval"}
    with purpose.using("work"):
        assert purpose.current() == "work"


def test_every_gateway_request_header_set_carries_the_purpose(monkeypatch):
    monkeypatch.setenv(purpose.ENV, "discover")
    got = gateway_key.headers({purpose.ENV: "discover", gateway_key.ENV_VAR: "sk-x"})
    assert got == {"Authorization": "Bearer sk-x", "x-litellm-tags": "purpose:discover"}


def test_a_completion_sends_the_purpose_header(monkeypatch):
    sent = {}

    class R:
        status_code = 200
        headers = {}
        text = ""

    def post(url, json=None, timeout=None, headers=None):
        sent.update(headers or {})
        return R()
    monkeypatch.setattr(completion.httpx, "post", post)
    monkeypatch.setenv(purpose.ENV, "eval")
    completion._send("http://127.0.0.1:1", {"model": "m"}, 1.0)
    assert sent.get("x-litellm-tags") == "purpose:eval"


@pytest.mark.parametrize("verb,want", [("code", "work"), ("decide", "work"), ("svg", "work"),
                                       ("discover", "discover"), ("watchdog", "watchdog"),
                                       ("reverify", "eval")])
def test_a_cli_verb_sets_its_purpose(verb, want):
    from harness import cli
    assert cli.VERB_PURPOSE[verb] == want


def test_the_cli_sets_the_verbs_purpose_unless_the_parent_set_one(monkeypatch):
    from harness import cli
    monkeypatch.delenv(purpose.ENV, raising=False)
    monkeypatch.setattr(cli, "build_parser", lambda: _parser("code"))
    cli.main(["code"])
    assert purpose.current() == "work"
    monkeypatch.setenv(purpose.ENV, "smoke")
    cli.main(["code"])
    assert purpose.current() == "smoke"


def _parser(verb):
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command")
    sub.add_parser(verb).set_defaults(func=lambda a: 0)
    return ap


def test_an_eval_run_sends_eval(monkeypatch):
    from evals import run
    monkeypatch.setenv(purpose.ENV, "discover")
    monkeypatch.setattr(run, "_main", lambda args: 0)
    monkeypatch.setattr(run, "parse_args", lambda argv: None)
    run.main([])
    assert purpose.current() == "eval"


def test_the_watchdog_sends_watchdog(monkeypatch):
    from harness import watchdog
    monkeypatch.delenv(purpose.ENV, raising=False)
    monkeypatch.setattr(watchdog, "wake", lambda conn, act: None)

    class A:
        act = False
        dry_run = True
    watchdog.run(A())
    assert purpose.current() == "watchdog"


def test_the_node_smoke_request_is_tagged_smoke(monkeypatch):
    import httpx

    from harness import nodes
    sent = {}
    monkeypatch.setattr(httpx, "post", lambda url, headers=None, **kw: sent.update(headers))
    nodes._ask("http://g", "sk", "m", 1.0)
    assert sent["x-litellm-tags"] == "purpose:smoke" and sent["Authorization"] == "Bearer sk"


def test_every_smoke_request_to_the_gateway_is_tagged():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    calls = [ln for ln in text.splitlines() if re.search(r'curl .*"\$G/', ln)]
    assert len(calls) >= 9
    assert [ln for ln in calls if '-H "$TAG"' not in ln] == []
    assert 'TAG="x-litellm-tags: purpose:smoke"' in text


# ---- delegation is work, and is counted even when it skips the gateway -----------


class Engine(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.headers_seen = []

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.headers_seen.append(dict(self.headers))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in ({"model": "Served-Q4", "choices": [{"index": 0, "delta": {"content": "ok"}}]},
                          {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 7}}):
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        data = json.dumps({"model": "Served-Q4", "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 7}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def engine(monkeypatch):
    srv = Engine()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(delegate, "route", lambda lane, chosen=None, via="": (
        "llamacpp:Served-Q4", serving.Route(srv.url, "Served-Q4", {})))
    monkeypatch.setattr(context, "served_ctx", lambda spec: None)
    monkeypatch.delenv(purpose.ENV, raising=False)
    yield srv
    srv.shutdown()
    srv.server_close()


def _requests():
    conn = ms.connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM gateway_requests")]
    finally:
        conn.close()


def test_a_delegation_straight_to_an_engine_is_logged_as_work_on_its_lane(engine):
    got = delegate.complete("code", "write add", delegated=True)
    assert got["text"] == "ok"
    rows = _requests()
    assert len(rows) == 1
    r = rows[0]
    assert (r["purpose"], r["lane"], r["alias"], r["client"]) == ("work", "code", "sohot-code",
                                                                  usage.DIRECT_CLIENT)
    assert (r["served"], r["spec"], r["stream"]) == ("Served-Q4", "llamacpp:Served-Q4", 1)
    assert (r["prompt_tokens"], r["completion_tokens"]) == (9, 7) and r["error_class"] == ""
    assert engine.headers_seen[0].get("x-litellm-tags") == "purpose:work"


def test_a_failed_delegation_straight_to_an_engine_is_logged_as_a_work_error(engine, monkeypatch):
    monkeypatch.setattr(completion, "complete_full", _boom)
    with pytest.raises(completion.CompletionError):
        delegate.complete("code", "write add", delegated=True)
    (r,) = _requests()
    assert (r["purpose"], r["error_class"], r["error_code"]) == ("work", "CompletionError", "crashed")


def _boom(*a, **kw):
    raise completion.CompletionError("engine fell over", "crashed")


def test_a_decide_straight_to_an_engine_is_logged_as_work(engine):
    schema = {"kind": {"type": "enum", "choices": ["ok", "no"], "description": "which"}}
    with pytest.raises(ValueError, match="no usable answer"):
        delegate.decide("is it ok", schema, delegated=True)
    (r,) = _requests()
    assert (r["purpose"], r["lane"], r["stream"]) == ("work", "decide", 0)


def test_a_delegation_through_the_gateway_is_left_to_the_gateway_to_log(engine, monkeypatch):
    monkeypatch.setenv(completion.GATEWAY_ENV, engine.url)
    delegate.complete("code", "write add", delegated=True)
    assert _requests() == []
    assert engine.headers_seen[0].get("x-litellm-tags") == "purpose:work"


def test_a_soh_lane_command_straight_to_an_engine_is_logged_as_work(engine):
    from types import SimpleNamespace

    from harness.commands import lanes
    spec, raw, _ = lanes._complete(SimpleNamespace(model=None, gateway=None), "svg", "a cat")
    assert raw == "ok"
    (r,) = _requests()
    assert (r["purpose"], r["lane"], r["client"], r["spec"]) == ("work", "svg",
                                                                 usage.DIRECT_CLIENT, spec)
