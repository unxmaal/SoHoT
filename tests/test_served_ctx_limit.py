"""The served context is a limit we chose, named when it binds rather than blamed on the reply budget or the gateway. #692."""
import json

import httpx
import pytest
import respx
import yaml

from evals import run as R
from evals.core import Case
from evals.runners.text import CompletionRunner
from harness import binding, completion, context, delegate, ds4, knobs, memory, reasons, runs
from harness import memory_store as ms
from tests import conftest

GW = "http://gw.test"
URL = f"{GW}/v1/chat/completions"
CODE = Case("add-two", "code", "write add", assertions={"checks": ["add(1, 2) == 3"]})
GIB = 1024 ** 3
OVERFLOW = ('gateway returned HTTP 400: {"error": {"code": 400, "message": "request (40000 tokens) '
            'exceeds the available context size (16384 tokens), try increasing it"}}')


def _reply(text, finish="stop", tokens=3, prompt=40):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": finish}],
                                     "usage": {"completion_tokens": tokens, "prompt_tokens": prompt}},
                          request=httpx.Request("POST", URL))


def _cut_at_context(ctx):
    """A server that stops every reply at its context, as llama-server does at n_ctx."""
    def answer(request):
        asked = json.loads(request.content)["max_tokens"]
        return _reply("def add(a, b):\n    return a -", finish="length", tokens=min(asked, ctx - 40))
    return answer


@respx.mock
def test_a_reply_cut_at_the_served_context_names_served_ctx_not_the_reply_budget():
    route = respx.post(URL).mock(side_effect=_cut_at_context(16384))
    row = CompletionRunner(GW, "org/x", max_tokens=32768, served_ctx=16384).run(CODE)
    assert json.loads(route.calls[0].request.content)["max_tokens"] < 16384
    assert row.failure_class == reasons.CONTEXT_EXCEEDED
    assert row.limit == "served_ctx>16384"


@respx.mock
def test_a_reply_cut_under_the_served_context_is_still_the_reply_budget():
    respx.post(URL).mock(return_value=_reply("def add(a, b):\n    return a -", finish="length", tokens=4000))
    row = CompletionRunner(GW, "org/x", max_tokens=4000, served_ctx=16384).run(CODE)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>4000"


@respx.mock
def test_the_served_tokenizer_sizes_the_room_left_for_the_reply():
    route = respx.post(URL).mock(return_value=_reply("def add(a, b): return a + b"))
    runner = CompletionRunner(GW, "org/x", max_tokens=32768, served_ctx=16384, count=lambda text: 1000)
    runner.run(CODE)
    assert json.loads(route.calls[0].request.content)["max_tokens"] <= 16384 - 2000


@respx.mock
def test_a_context_overflow_400_is_the_served_context_not_the_gateway():
    respx.post(URL).mock(return_value=httpx.Response(400, text=OVERFLOW[len("gateway returned HTTP 400: "):],
                                                     request=httpx.Request("POST", URL)))
    row = CompletionRunner(GW, "org/x", served_ctx=16384).run(CODE)
    assert row.failure_class == reasons.CONTEXT_EXCEEDED
    assert row.limit == "served_ctx>16384"


@pytest.mark.parametrize("text", [
    OVERFLOW,
    "gateway returned HTTP 400: This model's maximum context length is 16384 tokens (max_model_len)",
    "gateway returned HTTP 400: litellm.ContextWindowExceededError: litellm.BadRequestError: ...",
])
def test_classify_reads_a_context_overflow_400_as_a_limit(text):
    assert reasons.classify(text) == reasons.CONTEXT_EXCEEDED
    assert reasons.CLASSES[reasons.CONTEXT_EXCEEDED][1] == reasons.LIMIT


def test_a_400_that_is_not_about_context_is_still_the_gateway():
    assert reasons.classify("gateway returned HTTP 400: invalid model name") == reasons.REFUSED_BY_GATEWAY
    assert reasons.classify("gateway returned HTTP 400: n_ctx_slot = 4096") == reasons.REFUSED_BY_GATEWAY


@respx.mock
def test_climb_does_not_rerun_a_context_cut_case_past_the_served_context():
    route = respx.post(URL).mock(side_effect=_cut_at_context(16384))
    runner = CompletionRunner(GW, "org/x", served_ctx=16384)
    row = R.climb(runner, CODE, (4000, 16000, 32000, 65536))
    asked = [json.loads(c.request.content)["max_tokens"] for c in route.calls]
    assert max(asked) < 16384 and len(asked) == 3
    assert row.limit == "served_ctx>16384"


def test_the_kv_cap_scales_with_the_machine_so_a_96_gib_plan_is_not_held_at_8(monkeypatch):
    monkeypatch.delenv("LLAMACPP_KV_MAX_GIB", raising=False)
    monkeypatch.setattr(memory, "total_gb", lambda: 96.0)
    assert context.kv_cap_bytes() == 24 * GIB
    monkeypatch.setattr(memory, "total_gb", lambda: float(context.KV_MAX_RAM_GB))
    assert context.kv_cap_bytes() == context.KV_MAX_GIB * GIB
    monkeypatch.setenv("LLAMACPP_KV_MAX_GIB", "4")
    assert context.kv_cap_bytes() == 4 * GIB


GEMMA3 = {"general.architecture": "gemma3", "gemma3.context_length": 131072, "gemma3.block_count": 48,
          "gemma3.embedding_length": 3840, "gemma3.attention.head_count": 16,
          "gemma3.attention.head_count_kv": 8, "gemma3.attention.key_length": 256,
          "gemma3.attention.value_length": 256, "gemma3.attention.sliding_window": 1024}


def test_sliding_window_layers_are_costed_at_their_window_not_the_whole_context():
    # gemma3 is 5 local layers to 1 global: 8 of 48 layers grow with the context.
    assert context.kv_bytes_per_token(GEMMA3) == 8 * 8 * 512 * 2
    assert context.swa_bytes(GEMMA3) == 40 * 8 * 512 * 2 * (1024 + context.SWA_UBATCH)
    got = context.choose(GEMMA3, 0, 100 * GIB, kv_cap=8 * GIB)
    assert got.ctx > 100_000


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/context.py:SWA_PERIOD")
def test_an_arch_with_a_window_but_no_known_pattern_is_costed_as_full_attention():
    meta = {**GEMMA3, "general.architecture": "newarch",
            **{k.replace("gemma3.", "newarch."): v for k, v in GEMMA3.items() if k.startswith("gemma3.")}}
    assert context.kv_bytes_per_token(meta) == 48 * 8 * 512 * 2
    assert context.swa_bytes(meta) == 0


def test_a_per_layer_sliding_window_pattern_is_read_from_the_header():
    meta = {**GEMMA3, "gemma3.attention.sliding_window_pattern": [True, False] * 24}
    assert context.kv_bytes_per_token(meta) == 24 * 8 * 512 * 2


def test_ds4_context_holds_the_top_ladder_rung_and_the_largest_shipped_case_prompt():
    from evals import core
    # libyaml: the pure-Python loader spent seconds on the ~3800 shipped cases (#1146).
    pads = [int((yaml.load(f.read_text(encoding="utf-8"), Loader=core._LOADER).get("params") or {}).get("pad_tokens") or 0)
            for f in (knobs.REPO / "evals" / "cases").rglob("*.yaml")]
    top = max(max(completion.ladder(lane) or (0,)) for lane in completion.LADDER)
    assert max(pads) >= 32000
    assert ds4.DEFAULT_CTX >= top + max(pads) + ds4.STEP_ROOM


def test_a_larger_case_pad_grows_the_ds4_prompt_room(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "long64k.yaml").write_text("id: long64k\nparams:\n  pad_tokens: 64000\n", encoding="utf-8")
    (tmp_path / "agent" / "short.yaml").write_text("id: short\nparams:\n  max_steps: 4\n", encoding="utf-8")
    assert ds4.prompt_room(tmp_path) == 64000 + ds4.STEP_ROOM
    assert ds4.prompt_room(tmp_path / "missing") == ds4.STEP_ROOM


@respx.mock
def test_a_reasoning_only_reply_stopped_at_the_served_context_is_the_context_not_the_budget():
    respx.post(URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": None, "reasoning_content": "thinking"}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 4000, "prompt_tokens": 12384}}, request=httpx.Request("POST", URL)))
    row = CompletionRunner(GW, "org/x", max_tokens=4000, served_ctx=16384, count=lambda text: 1).run(CODE)
    assert row.failure_class == reasons.CONTEXT_EXCEEDED
    assert row.limit == "served_ctx>16384"


@respx.mock
def test_a_reasoning_only_reply_under_the_served_context_is_still_the_budget():
    respx.post(URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": None, "reasoning_content": "thinking"}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 4000, "prompt_tokens": 40}}, request=httpx.Request("POST", URL)))
    row = CompletionRunner(GW, "org/x", max_tokens=4000, served_ctx=16384, count=lambda text: 1).run(CODE)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>4000"


def test_the_served_ctx_knob_is_valued_in_tokens_like_the_limit_it_records():
    k = knobs.KNOBS["served_ctx"]
    assert k.default() >= context.FLOOR
    assert min(k.values) >= context.FLOOR
    assert "harness/context.py:KV_MAX_GIB" not in k.sites
    assert knobs.KNOBS["kv_cap"].sites[:2] == ("harness/context.py:KV_MAX_GIB", "harness/context.py:KV_MAX_RAM_GB")


def test_the_inventory_sees_table_keys_with_hyphens():
    found = set(knobs.inventory(knobs.REPO))
    for arch in context.SWA_PERIOD:
        site = f"harness/context.py:SWA_PERIOD[{arch}]"
        assert site in found and knobs.not_gating(site)
    assert knobs.resolve("harness/context.py:SWA_PERIOD[gpt-oss]") == context.SWA_PERIOD["gpt-oss"]


CJK = "漢字" * 300


def test_cap_counts_the_prompt_with_the_served_tokenizer_when_given_one():
    assert delegate.cap(16384, CJK, count=len) == 16384 - len(CJK)
    assert delegate.cap(16384, CJK) == 16384 - len(CJK) // delegate.CHARS_PER_TOKEN


def test_cap_falls_back_to_the_estimate_when_the_tokenizer_fails():
    def broken(text):
        raise httpx.ConnectError("gone")
    assert delegate.cap(16384, CJK, count=broken) == delegate.cap(16384, CJK)


def test_delegate_budget_asks_the_served_tokenizer(monkeypatch):
    monkeypatch.setattr(context, "served_ctx", lambda spec, *a, **k: 1000)
    monkeypatch.setattr(context, "_upstream", lambda spec, *a, **k: ("http://up", "m"))
    monkeypatch.setattr(completion, "token_counter", lambda base, model: len)
    with pytest.raises(delegate.Refused):
        delegate._budget("m", 500, CJK)


def test_the_ladder_rungs_use_the_served_tokenizer():
    assert R.rungs_for((4000, 16000), 16384, CJK, count=len) == (4000, 16384 - len(CJK))


def test_served_ctx_is_a_registered_knob_whose_limit_a_text_lane_records():
    k = knobs.KNOBS["served_ctx"]
    assert k.limit == "served_ctx" and k.predicate == knobs.MACHINE
    assert set(k.lanes) >= {"code", "agent"}
    for site in ("harness/ds4.py:DEFAULT_CTX",
                 "harness/vllm.py:METAL_MAX_MODEL_LEN", "harness/context.py:environ(LLAMACPP_CTX)"):
        assert site in k.sites


def test_binding_credits_served_ctx_not_the_reply_budget(tmp_path, monkeypatch):
    m = {"fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit",
         "arch": "arm64", "memory_gb": 96.0, "accelerator": "unified 96GB", "runtimes": "cpu,mlx",
         "ceiling_gb": 66.0, "versions": {}}
    conftest.stand_in_machine(monkeypatch, m)
    conn = ms.connect(tmp_path / "d.db")
    ms.remember_machine(conn, dict(m))
    rows = [{"candidate": "m", "case_id": f"c{i}", "passed": False, "seconds": 1.0,
             "failure_class": reasons.CONTEXT_EXCEEDED, "limit": "served_ctx>16384"} for i in range(4)]
    runs.record(conn, "runs/r1-code", {"receipt": {"modality": "code"},
                                       "environment": {"hw_model": m["hw_model"], "os": m["os"], "arch": "arm64"},
                                       "specs": {"m": "m"}, "rows": rows}, at=1_800_000_000.0 - 86400)
    found = binding.count(conn, now=1_800_000_000.0)
    conn.close()
    got = {(r["knob"], r["lane"]): r for r in found}
    assert got[("served_ctx", "code")]["hits"] == 4 and got[("served_ctx", "code")]["binding"]
    assert got[("reply_budget", "code")]["hits"] == 0
