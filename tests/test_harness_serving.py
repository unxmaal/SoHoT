"""Issue #190: which server produced the tokens is part of the exam."""
import re
from pathlib import Path

import pytest

from evals.core import Receipt, comparable
from harness import serving

REPO = Path(__file__).parent.parent


def receipt(**kw):
    base = dict(modality="code", case_ids=["a"], tier="measure",
                repeat=1, sampling={}, gateway="http://gw",
                instruments={"serving": "mlx_lm.server"})
    base.update(kw)
    return Receipt(**base)


def test_the_default_is_what_the_launcher_actually_starts():
    """RULE #237, sixth instance. The engine name lived only in a shell line;
    a second copy in Python that nothing compares is how that pair drifts."""
    text = (REPO / "scripts" / "serve-mlx.sh").read_text(encoding="utf-8")
    started = re.search(r"exec\s+uv\s+run\s+python\s+-m\s+(\S+)", text)
    assert started, "serve-mlx.sh no longer execs a recognisable server"
    from importlib import import_module
    assert import_module(started.group(1)).WRAPS == serving.DEFAULT


def test_an_unset_variable_gives_the_default():
    assert serving.text_engine({}) == serving.DEFAULT


def test_an_empty_variable_gives_the_default():
    """An exported-but-empty variable is how a shell passes 'unset'."""
    assert serving.text_engine({serving.ENV_VAR: ""}) == serving.DEFAULT
    assert serving.text_engine({serving.ENV_VAR: "   "}) == serving.DEFAULT


def test_a_config_line_names_a_different_engine():
    """The whole claim under test: a new method costs a config line."""
    assert serving.text_engine({serving.ENV_VAR: "vllm-mlx"}) == "vllm-mlx"


def test_two_engines_are_not_one_table():
    """The point of recording it. Before this, swapping the engine left the
    receipt byte-identical and comparable() said 'same exam'."""
    ok, why = comparable(receipt(),
                         receipt(instruments={"serving": "vllm-mlx"}))
    assert not ok
    assert "serving" in why or "vllm-mlx" in why


def test_the_same_engine_still_compares():
    """The negative half. An axis that refuses everything ranks nothing."""
    ok, _ = comparable(receipt(), receipt())
    assert ok


def test_a_receipt_without_the_key_does_not_block_an_old_one():
    """Receipts written before #190 carry no `serving`. comparable() compares
    only keys both runs have, so history stays rankable rather than being
    invalidated by a field that did not exist when it was recorded."""
    ok, _ = comparable(receipt(instruments={}), receipt())
    assert ok


# ---- vllm: specs and the one engine that drops a schema. #310, #572, #596 ----

def test_vllm_url_defaults_and_moves_to_vllm_port():
    assert serving.vllm_url({}) == "http://127.0.0.1:8086"
    assert serving.vllm_url({"VLLM_PORT": " 9001 "}) == "http://127.0.0.1:9001"
    assert serving.vllm_url({"VLLM_PORT": "abc"}) == serving.VLLM_URL
    assert serving.vllm_url({"VLLM_PORT": None}) == serving.VLLM_URL


def test_vllm_url_reads_the_process_environment_only_when_given_none(monkeypatch):
    monkeypatch.setenv("VLLM_PORT", "9002")
    assert serving.vllm_url() == "http://127.0.0.1:9002"
    assert serving.vllm_url({}) == serving.VLLM_URL


def test_vllm_engine_defaults_to_the_first_and_accepts_each_known():
    for environ in ({}, {"VLLM_ENGINE": "  "}, {"VLLM_ENGINE": None}):
        assert serving.vllm_engine(environ) == "vllm-mlx"
    assert serving.vllm_engine({"VLLM_ENGINE": " vllm-metal "}) == "vllm-metal"


def test_vllm_engine_reads_the_process_environment_only_when_given_none(monkeypatch):
    monkeypatch.setenv("VLLM_ENGINE", "vllm-metal")
    assert serving.vllm_engine() == "vllm-metal"
    assert serving.vllm_engine({}) == "vllm-mlx"


def test_an_unknown_vllm_engine_is_refused_naming_the_choices():
    with pytest.raises(ValueError) as e:
        serving.vllm_engine({"VLLM_ENGINE": "tgi"})
    assert str(e.value) == "VLLM_ENGINE=tgi is not one of vllm-mlx, vllm-metal"


def test_only_mlx_lm_server_drops_the_schema():
    for base in ("http://127.0.0.1:8081", "http://127.0.0.1:8081/",
                 "http://127.0.0.1:8081/v1", "http://127.0.0.1:8081/v1/"):
        assert serving.drops_schema(base, {}), base
    assert not serving.drops_schema("http://127.0.0.1:8082/v1", {})
    assert not serving.drops_schema("/v1http://127.0.0.1:8081", {})
    assert not serving.drops_schema("http://127.0.0.1:8081/v1", {"TEXT_ENGINE": "vllm"})


def _config(tmp_path, *entries):
    import yaml
    path = tmp_path / "gateway.yaml"
    path.write_text(yaml.safe_dump({"model_list": [
        {"model_name": name, "litellm_params": {"model": "openai/x", "api_base": base}}
        for name, base in entries]}), encoding="utf-8")
    return path


def test_an_alias_fronting_vllm_names_the_engine_from_the_environment_given(tmp_path):
    cfg = _config(tmp_path, ("fast", "http://127.0.0.1:9005/v1/"))
    env = {"VLLM_PORT": "9005", "VLLM_ENGINE": "vllm-metal"}
    assert serving.engine_for("fast", env, cfg) == "vllm-metal"
    assert serving.engine_for("vllm:org/m", env, cfg) == "vllm-metal"


def test_a_vllm_spec_routes_to_the_vllm_server_with_its_sampling():
    assert serving.route("vllm: org/m ,temperature=0") == serving.Route(
        serving.vllm_url(), "org/m", {"temperature": 0.0})
    with pytest.raises(ValueError, match="names no model; vllm:<repo id>"):
        serving.route("vllm: ")


def test_a_gguf_stem_is_the_fetched_one_else_the_hub_one(monkeypatch):
    from harness import gguf
    monkeypatch.setattr(gguf, "fetched", lambda repo: {"org/a": "fa"}.get(repo))
    monkeypatch.setattr(gguf, "hub_stem", lambda repo: {"org/b": "hb"}.get(repo))
    assert (serving.gguf_stem("org/a"), serving.gguf_stem("org/b"), serving.gguf_stem("org/c")) == (
        "fa", "hb", None)


def test_an_alias_stays_on_the_gateway_even_when_a_stem_would_match(tmp_path, monkeypatch):
    from harness.completion import DEFAULT_GATEWAY
    monkeypatch.setattr(serving, "gguf_stem", lambda name: "stem")
    cfg = _config(tmp_path, ("org/listed", "http://127.0.0.1:8081/v1"))
    assert serving.route("q3-4b", config=cfg).base == DEFAULT_GATEWAY
    assert serving.route("org/Listed", config=cfg).base == DEFAULT_GATEWAY
    assert serving.route("org/unlisted", config=cfg).model == "stem"


def test_a_repo_id_keeps_its_own_stem_and_sampling(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "gguf_stem", lambda name: "stem" if name == "org/g" else None)
    cfg = _config(tmp_path, ("alias", "http://127.0.0.1:8081/v1"))
    assert serving.route("org/g", config=cfg).model == "stem"
    assert serving.route("org/x,temperature=0.5", config=cfg).sampling == {"temperature": 0.5}


def test_the_schema_check_reads_the_config_and_route_it_is_given(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEWAY_CONFIG", raising=False)
    monkeypatch.delenv("LLAMACPP_PORT", raising=False)
    sch = _config(tmp_path, ("sch-alias", "http://127.0.0.1:8082/v1/"))
    assert serving.enforces_schema("sch-alias", {}, sch)
    monkeypatch.setattr(serving, "gguf_stem", lambda name: "stem")
    listed = _config(tmp_path, ("org/repo-gguf", "http://127.0.0.1:8081/v1"))
    assert not serving.enforces_schema("org/Repo-GGUF", {}, listed)


def test_a_routed_upstream_with_a_trailing_slash_still_enforces_the_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "gguf_stem", lambda name: None)
    cfg = _config(tmp_path, ("alias", "http://127.0.0.1:8082/"))
    assert serving.enforces_schema("org/a-model", {}, cfg)
