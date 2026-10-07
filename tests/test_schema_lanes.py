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
