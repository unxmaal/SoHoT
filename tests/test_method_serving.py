"""#581: an adopted method is served by the lane commands, delegation and (as its base) the gateway alias."""
import json

import httpx
import pytest
import respx
import yaml

from harness import adopt, cli, completion, delegate, gateway, methods
from harness import memory_store as ms
from harness.commands import lanes as lanes_cmd

GW = "http://127.0.0.1:4000"
MLX = "http://127.0.0.1:8081"
GOOD_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="5" height="5"/></svg>'

CONFIG = {"model_list": [
    {"model_name": "q3-4b", "litellm_params": {
        "model": "openai/mlx-community/Qwen3-4B-Instruct-2507-4bit",
        "api_base": f"{MLX}/v1", "api_key": "not-needed"}},
]}


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(path))
    return path


def adopt_for(lane: str, spec: str) -> None:
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict(lane, "q3-4b", spec, True,
                                         "beats q3-4b, 8 gained against 0 lost, p=0.01"))
    finally:
        conn.close()


def answered(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}],
                                     "usage": {"completion_tokens": 3}})


# ---- adopt: a winning method is an adoption row ---------------------------------

def test_a_winning_method_gets_an_adoption_row_and_no_not_served_note():
    adopt_for("code", "plan:q3-4b")
    conn = ms.connect()
    try:
        assert adopt.current(conn)["code"]["spec"] == "plan:q3-4b"
        row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC").fetchone()
        assert row["outcome"] == "measured" and "not served" not in row["detail"]
    finally:
        conn.close()


# ---- methods.run: the one serving body -------------------------------------------

def test_a_plain_spec_is_one_call_and_no_method_metadata():
    asked = []
    text, meta = methods.run("q3-4b", "code", "x", lambda p, m: asked.append((p, m)) or "y")
    assert (text, meta, asked) == ("y", {}, [("x", "code")])


def test_plan_serves_two_calls_the_plan_without_the_lanes_prompt():
    asked = []

    def ask(prompt, modality):
        asked.append((prompt, modality))
        return "1. do it" if len(asked) == 1 else "answer"
    text, meta = methods.run("plan:q3-4b", "code", "write add", ask)
    assert text == "answer"
    assert meta == {"method": "plan", "base": "q3-4b", "calls": 2}
    assert asked[0] == (methods.PLAN_PROMPT.format(task="write add"), "")
    assert asked[1] == (methods.ANSWER_PROMPT.format(task="write add", plan="1. do it"), "code")


def test_best_of_serves_the_sample_the_lanes_own_check_ranks_highest():
    replies = iter(["not svg", GOOD_SVG, "<svg"])
    text, meta = methods.run("best-of:3:q3-4b", "svg", "a square", lambda p, m: next(replies))
    assert text == GOOD_SVG
    assert meta == {"method": "best-of", "base": "q3-4b", "calls": 3, "samples": 3, "chosen": 2}


def test_best_of_survives_a_failed_sample_and_fails_when_every_sample_does():
    calls = []

    def ask(prompt, modality):
        calls.append(1)
        if len(calls) == 1:
            raise completion.CompletionError("boom")
        return "def f(): pass"
    text, meta = methods.run("best-of:2:q3-4b", "code", "x", ask)
    assert text == "def f(): pass" and meta["chosen"] == 2 and meta["calls"] == 2

    def dead(prompt, modality):
        raise completion.CompletionError("down")
    with pytest.raises(completion.CompletionError, match="down"):
        methods.run("best-of:2:q3-4b", "code", "x", dead)


def test_a_trace_method_is_not_a_text_method():
    with pytest.raises(ValueError, match="soh svg"):
        methods.run("trace:mflux:z-image-turbo", "svg", "x", lambda p, m: "")


# ---- lane commands --------------------------------------------------------------

@respx.mock
def test_soh_code_runs_an_adopted_plan_as_two_calls_through_the_base_route(capsys):
    adopt_for("code", "plan:q3-4b")
    hit = respx.post(f"{GW}/v1/chat/completions").mock(
        side_effect=[answered("1. add"), answered("def add(a, b):\n    return a + b\n")])
    assert cli.main(["code", "write add", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "def add" in out["body"]
    assert out["method"] == {"method": "plan", "base": "q3-4b", "calls": 2}
    sent = [json.loads(c.request.content) for c in hit.calls]
    assert [s["model"] for s in sent] == ["q3-4b", "q3-4b"]
    assert "Follow this plan" in sent[1]["messages"][-1]["content"]


@respx.mock
def test_soh_svg_runs_an_adopted_best_of_and_says_which_sample_it_kept(capsys, tmp_path):
    adopt_for("svg", "best-of:3:q3-4b")
    hit = respx.post(f"{GW}/v1/chat/completions").mock(
        side_effect=[answered("no"), answered(GOOD_SVG), answered("no")])
    assert cli.main(["svg", "a square", "-o", str(tmp_path / "s.svg"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["method"]["chosen"] == 2 and out["method"]["calls"] == 3
    assert len(hit.calls) == 3
    assert (tmp_path / "s.svg").read_text(encoding="utf-8").startswith("<svg")


def test_soh_svg_runs_an_adopted_trace_with_its_engine_and_preset(monkeypatch):
    adopt_for("svg", "trace-icon:mflux:z-image-turbo")
    seen = {}

    def traced(a, preset="illustration", method=None):
        seen.update(engine=a.engine, preset=preset, method=method)
        return 0
    monkeypatch.setattr(lanes_cmd, "_svg_by_tracing", traced)
    assert cli.main(["svg", "a fox"]) == 0
    assert seen["engine"] == "mflux:z-image-turbo" and seen["preset"] == "icon"
    assert seen["method"]["method"] == "trace-icon"


# ---- delegation -----------------------------------------------------------------

def test_delegate_complete_runs_an_adopted_plan_and_reports_its_cost(monkeypatch):
    adopt_for("code", "plan:q3-4b")
    sent = []

    def full(prompt, model, gateway="", **kw):
        sent.append((model, gateway, kw.get("modality"), kw.get("system")))
        return completion.Completion("1. add" if len(sent) == 1 else "def add(): pass",
                                     usage={"prompt_tokens": 5, "completion_tokens": 4},
                                     timing={"ttft_s": 0.1}, model="Qwen3-4B")
    monkeypatch.setattr(completion, "complete_full", full)
    got = delegate.complete("code", "write add", system="Be terse.")
    assert got["text"] == "def add(): pass" and got["spec"] == "plan:q3-4b"
    assert got["method"] == {"method": "plan", "base": "q3-4b", "calls": 2}
    assert [s[:2] for s in sent] == [("q3-4b", GW), ("q3-4b", GW)]
    assert sent[1][3] == "Be terse."
    assert (got["prompt_tokens"], got["completion_tokens"]) == (10, 8)


def test_thinking_false_reaches_both_calls_of_a_plan(monkeypatch):
    adopt_for("code", "plan:q3-4b")
    templates = []

    def full(prompt, model, gateway="", **kw):
        templates.append(kw.get("template"))
        return completion.Completion("x")
    monkeypatch.setattr(completion, "complete_full", full)
    delegate.complete("code", "write add", thinking=False)
    assert len(templates) == 2
    assert all(t and t.get("enable_thinking") is False for t in templates)


def test_the_context_cap_applies_to_each_call_of_a_method(monkeypatch):
    from harness import context
    adopt_for("code", "plan:q3-4b")
    seen = []
    monkeypatch.setattr(context, "served_ctx", lambda spec: seen.append(spec) or 4096)

    def full(prompt, model, gateway="", **kw):
        return completion.Completion("p" * 40000 if "Before answering" in prompt else "x")
    monkeypatch.setattr(completion, "complete_full", full)
    with pytest.raises(delegate.Refused, match=r"call 2 of plan:q3-4b \(the answer\)"):
        delegate.complete("code", "write add", max_tokens=2000)
    assert set(seen) == {"q3-4b"}


def test_a_methods_exhausted_budget_names_the_call_that_ran_out(monkeypatch):
    from harness import reasons
    adopt_for("code", "plan:q3-4b")
    replies = []

    def full(prompt, model, gateway="", **kw):
        replies.append(1)
        if len(replies) == 1:
            raise completion.CompletionError("spent the whole budget on reasoning (812 reasoning tokens)",
                                             reasons.TOKEN_BUDGET_EXHAUSTED)
        return completion.Completion("x")
    monkeypatch.setattr(completion, "complete_full", full)
    with pytest.raises(completion.CompletionError, match=r"call 1 of plan:q3-4b \(the plan\).*812.*thinking=false"):
        delegate.complete("code", "write add")


def test_local_complete_carries_the_methods_cost(monkeypatch):
    mcp_server = pytest.importorskip("harness.mcp_server")
    adopt_for("code", "best-of:2:q3-4b")
    monkeypatch.setattr(completion, "complete_full",
                        lambda *a, **k: completion.Completion("def f(): pass"))
    got = mcp_server.local_complete(prompt="write f", lane="code")
    assert got.method == {"method": "best-of", "base": "q3-4b", "calls": 2,
                          "samples": 2, "chosen": 1}


def test_delegate_refuses_a_lane_that_serves_a_trace_method():
    adopt_for("svg", "trace:mflux:z-image-turbo")
    with pytest.raises(delegate.Refused, match="soh svg"):
        delegate.complete("svg", "a fox")


def test_a_plain_delegation_carries_no_method(monkeypatch):
    monkeypatch.setattr(completion, "complete_full", lambda *a, **k: completion.Completion("x"))
    assert delegate.complete("code", "x")["method"] is None


# ---- the gateway alias keeps serving the base -----------------------------------

def test_the_lane_alias_serves_the_methods_base_model(config):
    adopt_for("code", "plan:q3-4b")
    got = {e["model_name"]: e["litellm_params"] for e in gateway.served(config)["model_list"]}
    assert got["sohot-code"] == got["q3-4b"]
