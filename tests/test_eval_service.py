"""The structured-output text server on Apple Silicon. Issue #286.

mlx_lm.server ignores `response_format`, so a client that needs schema-valid
JSON is routed to llama-server, which enforces it (RULE #326).
"""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SERVE = REPO / "scripts" / "serve-eval.sh"
LAUNCHD = REPO / "scripts" / "launchd.sh"
MAC = REPO / "gateway" / "config.yaml"
FETCH = REPO / "scripts" / "fetch-gguf.sh"


def _entries():
    body = yaml.safe_load(MAC.read_text(encoding="utf-8"))
    return [(e["model_name"], e["litellm_params"]) for e in body["model_list"]]


def _default_port() -> str:
    m = re.search(r'LLAMACPP_PORT="\$\{LLAMACPP_PORT:-(\d+)\}"',
                  SERVE.read_text(encoding="utf-8"))
    assert m, "serve-eval.sh must default LLAMACPP_PORT"
    return m.group(1)


def test_the_eval_server_is_a_launchd_service():
    services = re.search(r'^SERVICES="([^"]+)"',
                         LAUNCHD.read_text(encoding="utf-8"), re.M).group(1)
    assert "eval" in services.split()


def test_the_eval_server_is_llama_server_and_not_a_second_copy_of_it():
    text = SERVE.read_text(encoding="utf-8")
    assert "exec scripts/serve-llamacpp.sh" in text


def test_the_eval_port_is_not_the_mlx_port():
    assert _default_port() != "8081", "mlx_lm.server holds 8081 on this machine"


def test_every_eval_alias_reaches_the_eval_server():
    """Gauntlet #2: the port is written in the script and in the config, so
    the two copies are read and compared rather than trusted."""
    port = _default_port()
    evals = [(n, p) for n, p in _entries() if n.startswith("eval-")]
    assert evals, "no eval-* alias in gateway/config.yaml"
    for name, params in evals:
        assert params["api_base"] == f"http://127.0.0.1:{port}/v1", name


def test_no_other_alias_reaches_the_eval_server():
    """A non-eval alias on this port would silently lose the MLX engine."""
    port = _default_port()
    for name, params in _entries():
        if not name.startswith("eval-"):
            assert f":{port}/" not in params["api_base"], name


def test_the_eval_server_unloads_when_idle():
    """Two resident servers on a 32 GB machine is the RULE #193 crash shape."""
    text = (REPO / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")
    assert "--sleep-idle-seconds" in text
    assert "LLAMACPP_SLEEP_IDLE=-1" not in SERVE.read_text(encoding="utf-8")


def test_weights_are_fetched_into_the_flat_directory_the_router_reads():
    text = FETCH.read_text(encoding="utf-8")
    assert "$HF_HOME/gguf" in text
    assert "--local-dir" in text


def test_the_context_size_is_always_explicit():
    """With none given, llama-server sized a 4B model's cache to 151,808
    tokens per slot, about 21 GB, and nearly wedged a 32 GB machine."""
    text = (REPO / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")
    m = re.search(r'--ctx-size "\$\{LLAMACPP_CTX:-(\d+)\}"', text)
    assert m, "serve-llamacpp.sh must pass --ctx-size"
    assert int(m.group(1)) <= 32768
