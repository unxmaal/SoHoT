"""#481: real use through the gateway becomes rows in the store, with no text unless asked."""
import asyncio
import importlib.util
import threading
import time
from pathlib import Path

import pytest
import yaml

from harness import memory_store as ms
from harness import paths, usage

REPO = Path(__file__).resolve().parents[1]
SECRET = "SECRET-PROMPT-TEXT"
TOOLS = [{"type": "function", "function": {"name": "read", "parameters": {"type": "object"}}}]


def call(name="read", args='{"path": "a"}'):
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": args}}


def payload(*, alias="sohot-code", stream=None, start=1000.0, first=1000.4, end=1001.0,
            ua="opencode/1.2.3 ai-sdk", key_alias=None, tools=TOOLS, ok=True,
            error_class="", error_code="", prompt=12, completion=7, call_type="acompletion"):
    """kwargs as LiteLLM 1.100.0's proxy hands a CustomLogger, trimmed to the fields read."""
    slo = {
        "model_group": alias, "model": "openai/mlx-community/Qwen3-4B", "stream": stream,
        "api_base": "http://127.0.0.1:8081/v1", "call_type": call_type,
        "prompt_tokens": prompt, "completion_tokens": completion,
        "startTime": start, "completionStartTime": first if stream else end, "endTime": end,
        "user_agent": ua, "status": "success" if ok else "failure",
        "metadata": {"user_api_key_alias": key_alias, "user_agent": ua,
                     "user_api_key_hash": "litellm_proxy_master_key"},
        "error_information": {"error_class": error_class, "error_code": error_code,
                              "error_message": f"boom {SECRET}"},
        "messages": [{"role": "user", "content": SECRET}],
        "response": {"choices": [{"message": {"content": SECRET}}]},
        "error_str": None if ok else f"litellm.{error_class}: {SECRET}",
    }
    return {"standard_logging_object": slo, "call_type": call_type, "stream": bool(stream),
            "optional_params": {"tools": tools} if tools else {},
            "messages": [{"role": "user", "content": SECRET}]}


def response(calls=(), finish="tool_calls", content=SECRET):
    """A ModelResponse as model_dump() gives it: OpenAI shape on every route."""
    return {"id": "x", "object": "chat.completion", "model": "sohot-code",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": content,
                                     "tool_calls": list(calls) or None}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7}}


class Dumped:
    """Something with model_dump(), as litellm's ModelResponse is."""

    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return self._d


# ---- what one request becomes -------------------------------------------------


def test_a_request_becomes_a_row_with_alias_lane_served_model_tokens_and_latency():
    r = usage.row(payload(), Dumped(response([call()])))
    assert r["alias"] == "sohot-code" and r["lane"] == "code"
    assert r["served"] == "openai/mlx-community/Qwen3-4B"
    assert r["at"] == 1000.0 and r["total_s"] == pytest.approx(1.0)
    assert (r["prompt_tokens"], r["completion_tokens"]) == (12, 7)
    assert r["finish_reason"] == "tool_calls" and r["error_class"] == ""
    assert r["call_type"] == "acompletion" and r["stream"] == 0


def test_no_prompt_or_completion_text_reaches_the_row():
    r = usage.row(payload(ok=False, error_class="InternalServerError"), None)
    r2 = usage.row(payload(), Dumped(response([call()])))
    assert SECRET not in repr(r) and SECRET not in repr(r2)


def test_ttft_is_recorded_for_a_stream_and_not_invented_for_a_non_stream():
    assert usage.row(payload(stream=True), response())["ttft_s"] == pytest.approx(0.4)
    assert usage.row(payload(stream=None), response())["ttft_s"] is None


def test_each_tool_call_is_valid_only_if_it_parses_and_names_an_offered_tool():
    calls = [call(), call(args="{not json"), call(name="write"), call(args='"a string"')]
    r = usage.row(payload(), response(calls))
    assert (r["tool_calls"], r["tool_calls_valid"]) == (4, 1)


def test_a_tool_call_when_no_tool_was_offered_is_invalid():
    r = usage.row(payload(tools=None), response([call()]))
    assert (r["tool_calls"], r["tool_calls_valid"]) == (1, 0)


def test_a_failure_records_its_error_class_and_code():
    r = usage.row(payload(ok=False, error_class="ContextWindowExceededError",
                          error_code="400", prompt=0, completion=0), None)
    assert r["error_class"] == "ContextWindowExceededError" and r["error_code"] == "400"
    assert r["tool_calls"] == 0 and r["finish_reason"] == ""


def test_a_failure_with_no_error_class_still_counts_as_an_error():
    r = usage.row(payload(ok=False), None)
    assert r["error_class"] == "error"


def test_client_is_the_key_alias_when_set_else_the_user_agent_product():
    assert usage.row(payload(), response())["client"] == "opencode/1.2.3"
    assert usage.row(payload(key_alias="laptop"), response())["client"] == "laptop"
    assert usage.row(payload(ua=None), response())["client"] == ""


def test_a_non_lane_alias_has_no_lane_and_the_spec_is_what_the_gateway_was_told():
    specs = {"sohot-code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}
    assert usage.row(payload(), response(), specs)["spec"] == specs["sohot-code"]
    r = usage.row(payload(alias="q3-4b"), response(), specs)
    assert r["lane"] == "" and r["spec"] == "q3-4b"


def test_a_malformed_payload_gives_a_row_not_an_exception():
    r = usage.row({}, object())
    assert r["alias"] == "" and r["error_class"] == ""


# ---- the opt-in text sample ---------------------------------------------------


def test_a_text_sample_is_bounded():
    big = "x" * (usage.SAMPLE_CHARS * 3)
    kw = payload()
    kw["standard_logging_object"]["messages"] = [{"role": "user", "content": big}]
    s = usage.sample(kw, response(content=big))
    assert len(s["prompt"]) <= usage.SAMPLE_CHARS
    assert len(s["completion"]) <= usage.SAMPLE_CHARS


# ---- the store ----------------------------------------------------------------


def test_the_schema_carries_the_requests_and_samples_tables():
    conn = ms.connect()
    try:
        assert ms.SCHEMA_VERSION >= 44
        cols = {r[1] for r in conn.execute("PRAGMA table_info(gateway_requests)")}
        assert {"at", "alias", "lane", "served", "spec", "client", "prompt_tokens",
                "completion_tokens", "ttft_s", "total_s", "stream", "tool_calls",
                "tool_calls_valid", "finish_reason", "error_class"} <= cols
        assert {r[1] for r in conn.execute("PRAGMA table_info(gateway_samples)")} >= {
            "request_id", "prompt", "completion"}
    finally:
        conn.close()


def test_text_is_off_by_default_and_a_setting_turns_it_on():
    conn = ms.connect()
    try:
        assert usage.text_enabled(conn) is False
        usage.set_text(conn, True)
        assert usage.text_enabled(conn) is True
        usage.set_text(conn, False)
        assert usage.text_enabled(conn) is False
    finally:
        conn.close()


def _writer(**kw):
    w = usage.Writer(connect=kw.pop("connect", ms.connect), flush_s=0.01, **kw)
    w.start()
    return w


def _rows(table="gateway_requests"):
    conn = ms.connect()
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    finally:
        conn.close()


def test_the_writer_batches_rows_into_the_store_and_keeps_no_text_by_default():
    w = _writer()
    for _ in range(5):
        w.put(usage.row(payload(), response([call()])), usage.sample(payload(), response()))
    w.close()
    rows = _rows()
    assert len(rows) == 5 and rows[0]["alias"] == "sohot-code"
    assert _rows("gateway_samples") == []
    assert SECRET.encode() not in (paths.home() / "discovery.db").read_bytes()


def test_with_text_on_the_writer_keeps_a_bounded_number_of_samples(monkeypatch):
    monkeypatch.setattr(usage, "SAMPLE_ROWS", 3)
    conn = ms.connect()
    usage.set_text(conn, True)
    conn.close()
    w = _writer()
    for _ in range(5):
        w.put(usage.row(payload(), response()), usage.sample(payload(), response()))
    w.close()
    samples = _rows("gateway_samples")
    assert len(_rows()) == 5 and len(samples) == 3
    assert SECRET in samples[0]["prompt"]


def test_a_store_that_cannot_be_opened_never_raises_into_the_caller():
    def broken():
        raise RuntimeError("store is locked forever")
    w = _writer(connect=broken)
    w.put(usage.row(payload(), response()))
    w.close()
    assert w.dropped >= 1


def test_put_does_not_wait_for_the_store():
    """The gateway's event loop must not block on SQLite: put only enqueues."""
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return ms.connect()
    w = _writer(connect=slow)
    t = time.perf_counter()
    for _ in range(200):
        w.put(usage.row(payload(), response()))
    took = time.perf_counter() - t
    gate.set()
    w.close()
    assert took < 0.5
    assert len(_rows()) == 200


def test_a_full_queue_drops_rather_than_grows():
    gate = threading.Event()

    def slow():
        gate.wait(5)
        return ms.connect()
    w = _writer(connect=slow, maxsize=10)
    for _ in range(50):
        w.put(usage.row(payload(), response()))
    gate.set()
    w.close()
    assert w.dropped >= 30 and len(_rows()) <= 20


# ---- which store the gateway writes to ---------------------------------------


def test_the_gateway_writes_the_live_store_only_from_the_deploy_checkout(monkeypatch):
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: Path("/deploy"))
    assert usage.target() is None
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: None)
    assert usage.target() == ms.db_path()


def test_a_scratch_home_is_always_writable(monkeypatch):
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: Path("/deploy"))
    assert usage.target() == ms.db_path()


# ---- the LiteLLM callback ----------------------------------------------------


def _callback():
    spec = importlib.util.spec_from_file_location("usage_log", REPO / "gateway" / "usage_log.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_callback_hooks_enqueue_a_row_for_success_and_failure():
    mod = _callback()
    got = []

    class Fake:
        def put(self, row, sample=None):
            got.append((row, sample))
    cb = mod.UsageLog(writer=Fake())
    asyncio.run(cb.async_log_success_event(payload(), Dumped(response([call()])), None, None))
    asyncio.run(cb.async_log_failure_event(payload(ok=False, error_class="Timeout"),
                                           None, None, None))
    assert [g[0]["error_class"] for g in got] == ["", "Timeout"]


def test_the_callback_swallows_its_own_failure():
    mod = _callback()

    class Boom:
        def put(self, row, sample=None):
            raise RuntimeError("disk full")
    cb = mod.UsageLog(writer=Boom())
    asyncio.run(cb.async_log_success_event(payload(), response(), None, None))
    asyncio.run(cb.async_log_failure_event(None, None, None, None))


@pytest.mark.parametrize("name", ["config.yaml", "config.cuda.yaml"])
def test_both_gateway_configs_load_the_usage_callback(name):
    body = yaml.safe_load((REPO / "gateway" / name).read_text(encoding="utf-8"))
    assert "usage_log.proxy_handler_instance" in body["litellm_settings"]["callbacks"]
