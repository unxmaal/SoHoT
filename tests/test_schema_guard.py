"""A schema the backend cannot enforce is refused, not dropped. #315."""
import importlib.util
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("schema_guard",
                                              REPO / "gateway" / "schema_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

SCHEMA = {"type": "json_schema",
          "json_schema": {"name": "x", "schema": {"type": "object"}}}


def test_a_schema_sent_to_an_mlx_alias_is_refused_with_the_way_out():
    why = guard.refusal({"model": "q3-30b", "response_format": SCHEMA})
    assert "q3-30b" in why and "Qwen3-4B-Instruct-2507-Q4_K_M" in why
    # The way out names real ids, never a deprecated nickname. #670.
    assert "eval-4b" not in why


@pytest.mark.parametrize("data", [
    {"model": "eval-4b", "response_format": SCHEMA},
    {"model": "q3-30b"},
    {"model": "q3-30b", "response_format": {"type": "text"}},
])
def test_everything_else_passes(data):
    assert guard.refusal(data) == ""


def test_json_object_mode_is_refused_too():
    assert guard.refusal({"model": "local-large",
                          "response_format": {"type": "json_object"}})


def test_the_mac_gateway_loads_the_guard_and_the_cuda_one_does_not():
    """On the CUDA box every alias is llama-server, which enforces."""
    mac = yaml.safe_load((REPO / "gateway" / "config.yaml").read_text(encoding="utf-8"))
    cuda = yaml.safe_load((REPO / "gateway" / "config.cuda.yaml").read_text(encoding="utf-8"))
    assert "schema_guard.proxy_handler_instance" in (
        mac["litellm_settings"].get("callbacks") or [])
    assert "schema_guard.proxy_handler_instance" not in (
        (cuda.get("litellm_settings") or {}).get("callbacks") or [])


def test_an_entry_with_no_engine_refuses_rather_than_raising(tmp_path, monkeypatch):
    def entry(name, base, **extra):
        return {"model_name": name, **extra,
                "litellm_params": {"model": f"openai/{name}", "api_base": f"{base}/v1"}}
    cfg = tmp_path / "gateway.yaml"
    cfg.write_text(yaml.safe_dump({"model_list": [
        entry("enforcer", "http://far:8082", engine="llama-server"),
        entry("loose", "http://far:8081", engine="mlx_lm.server"),
        entry("mystery", "http://far:8083")]}), encoding="utf-8")
    monkeypatch.setattr(guard, "CONFIG", cfg)
    why = guard.refusal({"model": "loose", "response_format": SCHEMA})
    assert "enforcer" in why and "mystery" not in why
    why = guard.refusal({"model": "mystery", "response_format": SCHEMA})
    assert "mystery" in why and "engine" in why and "enforcer" in why
