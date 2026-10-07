"""A lane whose requests carry response_format resolves to an engine that enforces it. #572."""
import pytest

from harness import delegate, gateway, serving, winners

SCHEMA = {"urgent": {"type": "boolean", "description": "is it urgent"}}


class Sent(Exception):
    pass


def _lanes_that_send_a_schema(monkeypatch) -> set[str]:
    """Drive every delegated request and record which lanes put a response_format on it."""
    from harness import completion
    got: set[str] = set()

    def capture(prompt, **kw):
        if kw.get("response_format"):
            got.add(kw["modality"])
        raise Sent

    monkeypatch.setattr(completion, "complete_full", capture)
    monkeypatch.setattr(delegate, "_preflight", lambda *a, **k: None)
    for lane in gateway.TEXT_LANES:
        with pytest.raises(Sent):
            delegate.complete(lane, "p")
    with pytest.raises(Sent):
        delegate.decide("the server is down", SCHEMA)
    return got


def test_the_decide_lane_is_one_that_sends_a_schema(monkeypatch):
    assert "decide" in _lanes_that_send_a_schema(monkeypatch)


def test_every_schema_lane_resolves_to_an_engine_that_enforces_it(monkeypatch):
    monkeypatch.delenv("GATEWAY_CONFIG", raising=False)
    monkeypatch.delenv(serving.ENV_VAR, raising=False)
    for lane in sorted(_lanes_that_send_a_schema(monkeypatch)):
        spec = delegate.lane_model(lane)
        assert serving.engine_for(spec, environ={}) == serving.LLAMACPP, (
            f"the {lane} lane sends response_format but resolves to {spec}, "
            f"served by {serving.engine_for(spec, environ={})}, which ignores it")


def test_every_schema_lane_alias_reaches_llama_server(monkeypatch):
    monkeypatch.delenv("GATEWAY_CONFIG", raising=False)
    lanes = _lanes_that_send_a_schema(monkeypatch)
    served = {e["model_name"]: e["litellm_params"]
              for e in gateway.served(defaults=winners.typed())["model_list"]}
    for lane in lanes:
        params = served[gateway.LANE_ALIAS.format(lane)]
        assert params["api_base"].removesuffix("/v1") == serving.LLAMACPP_URL, lane


def test_the_schema_lanes_are_the_lanes_whose_requests_carry_one(monkeypatch):
    assert set(gateway.SCHEMA_LANES) == _lanes_that_send_a_schema(monkeypatch)


# --- the adopt tier ------------------------------------------------------------

def _store(tmp_path, spec, lane):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "d.db")
    if "/" in spec and ":" not in spec:
        ms.record(conn, ms.Seen(name=spec, source="feeds", lane=lane,
                                kind="weights", resolved=spec))
    return conn


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.delenv("GATEWAY_CONFIG", raising=False)
    monkeypatch.delenv(serving.ENV_VAR, raising=False)


@pytest.mark.parametrize("spec", ["mlx-community/Qwen3-4B-Instruct-2507-4bit", "q3-4b",
                                  "nimble:bespokelabs/Bespoke-Nimble-9B"])
def test_a_schema_lane_never_adopts_what_cannot_enforce_its_schema(tmp_path, mac, spec):
    from harness import adopt, reasons
    conn = _store(tmp_path, spec, "decide")
    adopt.record(conn, adopt.Verdict("decide", "eval-imajev-4b", spec, True, "won"))
    assert adopt.adopted(conn) == {}
    got = conn.execute("SELECT outcome, reason, failure_class, detail FROM verdicts "
                       "ORDER BY id DESC").fetchone()
    assert got["outcome"] == "queued", "a harness gap must not settle the candidate"
    assert got["reason"] == reasons.HARNESS
    assert got["failure_class"] == reasons.REFUSED_BY_GATEWAY
    assert "response_format" in got["detail"]


@pytest.mark.parametrize("spec", ["eval-imajev-4b", "llamacpp:imajev-4b-Q8_0"])
def test_a_schema_lane_adopts_what_llama_server_serves(tmp_path, mac, spec):
    from harness import adopt
    conn = _store(tmp_path, spec, "decide")
    adopt.record(conn, adopt.Verdict("decide", "q3-4b", spec, True, "won"))
    assert adopt.adopted(conn) == {"decide": spec}


def test_a_lane_without_a_schema_still_adopts_an_mlx_model(tmp_path, mac):
    from harness import adopt
    spec = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    conn = _store(tmp_path, spec, "code")
    adopt.record(conn, adopt.Verdict("code", "q3-4b", spec, True, "won"))
    assert adopt.adopted(conn) == {"code": spec}


# --- the eval ------------------------------------------------------------------

def _decide_case():
    from evals.core import Case
    return Case(id="d", modality="decide", prompt="p", params={"schema": {
        "urgent": {"type": "boolean", "description": "d"}}},
        assertions={"answers": {"urgent": True}})


def test_a_decide_case_is_never_scored_on_mlx_lm_server(monkeypatch, mac):
    """It would drop the schema silently and score a request the lane never sends."""
    from evals.runners.text import CompletionRunner
    from harness import completion, reasons
    sent = []
    monkeypatch.setattr(completion, "complete_full", lambda *a, **k: sent.append(k))
    r = CompletionRunner(serving.MLX_URL, "mlx-community/x").run(_decide_case())
    assert not sent
    assert not r.passed and r.failure_class == reasons.REFUSED_BY_GATEWAY
    assert "response_format" in r.detail


def test_the_same_port_under_llama_server_is_scored(monkeypatch):
    from evals.runners.text import CompletionRunner
    from harness import completion
    monkeypatch.setenv(serving.ENV_VAR, serving.LLAMACPP)
    sent = []

    def answer(*a, **k):
        sent.append(k)
        return completion.Completion('{"urgent": "A"}', {}, [])

    monkeypatch.setattr(completion, "complete_full", answer)
    CompletionRunner(serving.MLX_URL, "x").run(_decide_case())
    assert sent and sent[0]["response_format"]
