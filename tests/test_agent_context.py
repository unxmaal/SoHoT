"""The agent lane records and reports the context each candidate was served at. #498."""


from evals import run
from evals.core import summarize
from evals.runners.agent import AgentRunner
from evals.runners.base import RunnerError
from harness import context, downloads
from harness import memory_store as ms
from tests.test_agent_lane import case, serve  # noqa: F401
from tests.test_context import ORNITH, write_gguf

ROUTER = {"data": [
    {"id": "Ornith", "status": {"value": "unloaded", "args": [
        "llama-server", "--ctx-size", "262144", "--model", "x.gguf", "--parallel", "1"]}},
    {"id": "Other", "status": {"value": "unloaded", "args": ["llama-server"]}}]}


def test_a_llamacpp_candidate_is_served_at_what_the_router_will_launch():
    seen = []

    def get(url):
        seen.append(url)
        return ROUTER
    assert context.served_ctx("llamacpp:Ornith,temperature=0", get=get) == 262144
    assert seen[0].endswith("/models")


def test_a_gateway_alias_is_followed_to_its_router(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model_list:\n  - model_name: sohot-code\n    litellm_params:\n"
                   "      model: openai/Ornith\n      api_base: http://h:8082/v1\n",
                   encoding="utf-8")
    seen = []

    def get(url):
        seen.append(url)
        return ROUTER
    assert context.served_ctx("sohot-code", config=cfg, get=get) == 262144
    assert seen == ["http://h:8082/models"]


def test_the_store_answers_when_the_router_cannot(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    write_gguf(d / "Ornith.gguf", ORNITH)
    conn = ms.connect()
    downloads.record(conn, "org/o", downloads.GGUF, d / "Ornith.gguf", file="Ornith.gguf")
    context.plan(conn, budget=60 * 1024 ** 3)
    conn.close()

    def down(url):
        raise OSError("refused")
    assert context.served_ctx("llamacpp:Ornith", get=down) == 262144


def test_an_unknown_context_is_none_not_a_guess():
    assert context.served_ctx("claude-code:claude-opus-5-5") is None
    assert context.served_ctx("llamacpp:Nowhere", get=lambda url: {"data": []}) is None


def test_every_agent_row_carries_the_served_context(serve):  # noqa: F811
    s = serve([{"content": "The port is 8443."}])
    r = AgentRunner(s.url, "fake", served_ctx=262144).run(case("agent-read-service-port"))
    assert r.metrics["agent_ctx"] == 262144
    assert summarize([r])["fake"]["agent"]["ctx"] == 262144


def test_a_context_starved_error_row_still_says_what_it_was_served_at():
    runner = AgentRunner("http://127.0.0.1:9", "fake", served_ctx=16384)
    row = runner.failed(case("agent-long16k-fix-median"),
                        RunnerError("ContextWindowExceededError"))
    assert row.metrics["agent_ctx"] == 16384
    assert summarize([row])["fake"]["agent"]["ctx"] == 16384


def test_evals_run_asks_for_the_served_context(monkeypatch):
    monkeypatch.setattr(context, "served_ctx", lambda spec, **kw: 131072)
    r = run.build_runner("llamacpp:Ornith", "http://gw", None, modality="agent")
    assert r.served_ctx == 131072


def test_the_report_prints_each_candidates_served_context(capsys):
    summary = {"sohot-code": {"passed": 10, "total": 14, "pass_rate": 0.71, "metrics": {},
                              "agent": {"ctx": 16384, "completed": 10, "cases": 14}},
               "claude-code:opus": {"passed": 14, "total": 14, "pass_rate": 1.0, "metrics": {},
                                    "agent": {"completed": 14, "cases": 14}}}
    run.report(summary)
    out = capsys.readouterr().out
    assert "served context" in out
    assert "sohot-code: 16384" in out and "claude-code:opus: unknown" in out


