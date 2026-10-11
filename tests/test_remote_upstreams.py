"""An upstream on another machine, or a second engine on an unexpected port, is named by config, not by URL (#702)."""
import contextlib
import io
import json

import pytest
import yaml

from harness import completion, context, delegate, router, screen, serving

REMOTE_LLAMA = "http://studio2:8082"
REMOTE_MLX = "http://studio2:8081"


def _config(tmp_path, *entries, name="gateway.yaml"):
    rows = []
    for e in entries:
        model_name, base = e[0], e[1]
        extra = e[2] if len(e) > 2 else {}
        rows.append({"model_name": model_name, **extra,
                     "litellm_params": {"model": f"openai/{model_name}", "api_base": f"{base}/v1"}})
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"model_list": rows}), encoding="utf-8")
    return path


@pytest.fixture
def remote(tmp_path, monkeypatch):
    cfg = _config(tmp_path, ("far-gguf", REMOTE_LLAMA, {"engine": serving.LLAMACPP}),
                  ("far-mlx", REMOTE_MLX, {"engine": serving.DEFAULT}))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    monkeypatch.delenv("LLAMACPP_PORT", raising=False)
    monkeypatch.delenv("SOHOT_GATEWAY_URL", raising=False)
    return cfg


def test_a_remote_llama_server_alias_is_named_by_its_config_engine(remote):
    assert serving.engine_for("far-gguf", {}, remote) == serving.LLAMACPP
    assert serving.enforces_schema("far-gguf", {}, remote)


def test_a_remote_mlx_server_drops_the_schema(remote):
    assert serving.drops_schema(REMOTE_MLX + "/v1", {}, remote)
    assert not serving.drops_schema(REMOTE_LLAMA + "/v1", {}, remote)


def test_an_upstream_no_config_names_and_no_local_port_matches_is_a_loud_error(tmp_path):
    cfg = _config(tmp_path, ("mystery", "http://elsewhere:8081"))
    with pytest.raises(ValueError, match="engine"):
        serving.engine_for("mystery", {}, cfg)


def test_an_unknown_engine_key_is_refused(tmp_path):
    cfg = _config(tmp_path, ("odd", "http://elsewhere:8081", {"engine": "teapot"}))
    with pytest.raises(ValueError, match="teapot"):
        serving.engine_for("odd", {}, cfg)


def test_the_local_defaults_still_name_their_engines(tmp_path):
    cfg = _config(tmp_path, ("m", serving.MLX_URL), ("g", serving.LLAMACPP_URL))
    assert serving.engine_for("m", {}, cfg) == serving.DEFAULT
    assert serving.engine_for("g", {}, cfg) == serving.LLAMACPP


def test_discovered_repos_go_to_the_mlx_upstream_not_the_first_entry(tmp_path):
    cfg = _config(tmp_path, ("gguf", serving.LLAMACPP_URL), ("mlx", serving.MLX_URL))
    assert screen.gateway_routes(cfg)[1].rstrip("/").removesuffix("/v1") == serving.MLX_URL


def test_a_named_hot_swap_upstream_wins(tmp_path):
    cfg = _config(tmp_path, ("mlx", serving.MLX_URL), ("far", REMOTE_MLX, {"hot_swap": True}))
    assert screen.gateway_routes(cfg)[1].removesuffix("/v1") == REMOTE_MLX


def test_no_upstream_that_can_hot_swap_routes_nothing(tmp_path):
    cfg = _config(tmp_path, ("gguf", "http://127.0.0.1:8081", {"engine": serving.LLAMACPP}))
    assert screen.gateway_routes(cfg)[1] == ""


def test_a_remote_router_candidate_is_watched_on_its_own_base(remote, monkeypatch):
    got = router.upstream_for("far-gguf", route=lambda s, g: (REMOTE_LLAMA, "stem"))
    assert got == (REMOTE_LLAMA, "stem")
    assert router.model_for("far-gguf", route=lambda s, g: (REMOTE_LLAMA, "stem")) == "stem"
    asked = []

    def get(path, base=""):
        asked.append(base + path)
        return {"data": [{"id": "stem", "status": {"value": "loaded"}}]}
    monkeypatch.setattr(router, "_get", get)
    watch = router.Watch("stem", base=REMOTE_LLAMA)
    watch.look("a", "t")
    assert asked == [REMOTE_LLAMA + "/models"] and watch._held


def test_served_ctx_of_a_remote_router_that_does_not_answer_is_unknown(remote, monkeypatch):
    from harness import downloads
    monkeypatch.setattr(downloads, "store", lambda conn=None: contextlib.nullcontext(None))
    monkeypatch.setattr(context, "served", lambda c, stem: {"ctx": 8192, "ctx_slots": 1, "ctx_trained": 0})

    def down(url):
        raise OSError("timed out")
    assert context.served_ctx("far-gguf", get=down) is None
    local = _config(remote.parent, ("near", serving.LLAMACPP_URL), name="local.yaml")
    assert context.served_ctx("near", config=local, get=down) == 8192


def test_residency_is_asked_of_a_remote_upstream(remote):
    where = serving.Route(REMOTE_LLAMA, "stem", {})
    asked = []

    def get(url):
        asked.append(url)
        return {"data": [{"id": "stem", "status": {"value": "loaded"}}]}
    assert delegate.loaded(where, get=get)
    assert asked == [REMOTE_LLAMA + "/models"]


def test_the_local_lock_does_not_refuse_work_served_elsewhere(remote, monkeypatch):
    monkeypatch.setattr(delegate, "busy", lambda: "eval")
    monkeypatch.setattr(delegate, "running_job", lambda conn=None: "")
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: False)
    delegate._gate(serving.Route(REMOTE_LLAMA, "stem", {}))
    with pytest.raises(delegate.Refused):
        delegate._gate(serving.Route(serving.LLAMACPP_URL, "stem", {}))


def test_sohot_gateway_url_is_honoured_everywhere(remote, monkeypatch):
    far = "http://gateway.lan:4000"
    monkeypatch.setenv("SOHOT_GATEWAY_URL", far + "/")
    assert completion.gateway_url() == far
    assert serving.route("far-gguf", config=remote).base == far
    assert delegate.upstream(serving.Route(far, "far-gguf", {}), remote) == (REMOTE_LLAMA, "far-gguf")
    from harness import cli
    from evals import run as R
    parser = cli.build_parser()
    for argv in (["throughput", "--model", "m"], ["rubric", "run", "s"], ["benchmarks"]):
        assert parser.parse_args(argv).gateway == far, argv
    assert R._parser().parse_args([]).gateway == far
    from harness import throughput
    seen = []
    monkeypatch.setattr(throughput, "_gateway_post", lambda g, t: seen.append(g) or (lambda p: None))
    with contextlib.suppress(Exception):
        throughput.sweep("m", [], levels=())
    assert seen == [far]
