"""A node-served model's content identity names the node's build, settings and model sha256, never this machine's bytes. #1652, #1628."""
import pytest
import yaml

from evals import run as R
from harness import context, gateway, identity, node_state, nodes

MODEL = "Stem"
NODE_BASE = "http://node1.invalid:8083"
AWAY = "Mac14,12/macOS/arm64/0000000000a1"
HERE = "Mac17,15/macOS/arm64/0000000000b2"
SHA = "a" * 64
BASE = f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params:
      model: openai/{MODEL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
PROPS = {"build_info": "b12110-cd959bae9", "chat_template": "{{ messages }}", "total_slots": 2,
         "default_generation_settings": {"n_ctx": 32768, "id": 3, "is_processing": False,
                                         "params": {"temperature": 0.8, "top_k": 40}}}


def _nodes(tmp_path, monkeypatch, sha=SHA, machine=AWAY, lanes=()):
    entry = {"id": MODEL, "sha256": sha} if sha else MODEL
    raw = {"nodes": [{"name": "node1", "api_base": f"{NODE_BASE}/v1", "engine": "llama-server",
                      "models": [entry], "machine": machine, "lanes": list(lanes)}]}
    path = tmp_path / "nodes.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(nodes.ENV_VAR, str(path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, defaults={lane: MODEL for lane in lanes}, nodes=nodes.load())
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    monkeypatch.setattr(node_state, "read", lambda node: {"models": {MODEL: {"file": {"size": 7, "mtime_ns": 1, "sha256": SHA}}}})


@pytest.fixture
def props(monkeypatch):
    answers = {f"{NODE_BASE}/props?model={MODEL}": dict(PROPS)}
    monkeypatch.setattr(context, "_get_json", lambda url, key="": answers[url])
    return answers


@pytest.fixture
def local(tmp_path, monkeypatch):
    """This machine's llama-server and its own copy of the GGUF, the @local twin's bytes."""
    root = tmp_path / "srv"
    for d in ("bin", "lib", "gguf"):
        (root / d).mkdir(parents=True)
    (root / "bin" / "llama-server").write_bytes(b"binary v1")
    (root / "lib" / "libllama.0.dylib").write_bytes(b"lib v1")
    (root / "gguf" / f"{MODEL}.gguf").write_bytes(b"model v1")
    monkeypatch.setenv("LLAMACPP_BIN", str(root / "bin" / "llama-server"))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(root / "gguf"))
    monkeypatch.setattr(identity, "_linked", lambda exe: [])
    return root


@pytest.mark.parametrize("name, lanes", [(MODEL, ()), ("sohot-decide", ("decide",))])
def test_an_alias_a_node_serves_has_the_nodes_build_and_model_digest(tmp_path, monkeypatch, props, name, lanes):
    _nodes(tmp_path, monkeypatch, lanes=lanes)
    got = identity.served(name)
    assert "unresolved" not in got, got
    assert got["host"] == AWAY and got["node"] == "node1"
    assert got["runtime"] == {"llama.cpp": "12110"} and got["model"] == {MODEL: SHA}
    assert got["preset"]["settings"] == {"n_ctx": 32768, "params": {"temperature": 0.8, "top_k": 40}}
    assert got["preset"]["chat_template"]


@pytest.mark.parametrize("change", ["build", "settings", "template"])
def test_the_node_identity_moves_with_its_build_settings_or_template(tmp_path, monkeypatch, props, change):
    _nodes(tmp_path, monkeypatch)
    before = identity.digest_of(identity.served(MODEL))
    now = props[f"{NODE_BASE}/props?model={MODEL}"]
    if change == "build":
        now["build_info"] = "b12200-0000000"
    elif change == "settings":
        now["default_generation_settings"] = {**PROPS["default_generation_settings"], "params": {"temperature": 0.2}}
    else:
        now["chat_template"] = "{{ other }}"
    assert identity.digest_of(identity.served(MODEL)) != before


def test_a_router_node_without_per_model_props_is_read_from_its_own(tmp_path, monkeypatch):
    _nodes(tmp_path, monkeypatch)

    def get(url, key=""):
        if "?model=" in url:
            raise OSError("no per-model props")
        return PROPS
    monkeypatch.setattr(context, "_get_json", get)
    assert identity.served(MODEL)["runtime"] == {"llama.cpp": "12110"}


@pytest.mark.parametrize("why, setup", [
    ("sha256", lambda tmp, mp: _nodes(tmp, mp, sha="")),
    ("machine", lambda tmp, mp: _nodes(tmp, mp, machine="")),
    ("build", lambda tmp, mp: (_nodes(tmp, mp), mp.setattr(context, "_get_json", lambda url, key="": {})))])
def test_a_node_whose_bytes_cannot_be_named_has_no_identity(tmp_path, monkeypatch, props, why, setup):
    setup(tmp_path, monkeypatch)
    got = identity.served(MODEL)
    assert got.get("unresolved") and any(why in u for u in got["unresolved"]), got
    assert "runtime" not in got and "model" not in got


def test_the_local_twin_and_the_node_are_two_identities(tmp_path, monkeypatch, props, local):
    _nodes(tmp_path, monkeypatch)
    node = identity.served(MODEL)
    twin = identity.served(MODEL + nodes.LOCAL_SUFFIX)
    assert "unresolved" not in twin, twin
    assert set(twin["runtime"]) == {"llama-server", "libllama.0.dylib"} and "host" not in twin
    assert identity.digest_of(node) != identity.digest_of(twin)


def _ident(served_part):
    return {"digest": "d" * 64, "cases": {}, "parts": {"served": served_part}, "unresolved": []}


NODE_PART = {"engine": "llama-server", "node": "node1", "host": AWAY, "runtime": {"llama.cpp": "12110"},
             "model": {MODEL: SHA}}
LOCAL_PART = {"engine": "llama-server", "runtime": {"llama-server": "b" * 64}, "model": {f"{MODEL}.gguf": "c" * 64}}


def _record(spec, part, hosts):
    seen = {("http://127.0.0.1:4000", MODEL): {"machines": sorted(hosts)}} if hosts is not None else {}
    return R.served_identities({"llamacpp:" + MODEL: spec}, {spec: _ident(part)}, seen, HERE)["llamacpp:" + MODEL]


@pytest.mark.parametrize("hosts", [{HERE}, {AWAY, HERE}, set(), None])
def test_rows_the_local_copy_served_never_match_a_node_identity(hosts):
    got = _record(MODEL, NODE_PART, hosts)
    assert got["digest"] == "" and got["unresolved"]


@pytest.mark.parametrize("spec", [MODEL, "llamacpp:" + MODEL])
def test_a_key_a_node_served_does_not_keep_this_machines_bytes(spec):
    got = _record(spec, LOCAL_PART, {AWAY})
    assert got["digest"] == "" and got["unresolved"]
    assert got["parts"]["served"] == {"engine": "llama-server", "host": AWAY}


@pytest.mark.parametrize("spec, part, hosts", [(MODEL, NODE_PART, {AWAY}), (MODEL, LOCAL_PART, {HERE}),
                                               ("llamacpp:" + MODEL, LOCAL_PART, None)])
def test_rows_served_by_the_host_the_identity_names_keep_it(spec, part, hosts):
    assert _record(spec, part, hosts)["digest"] == "d" * 64


def test_a_models_entry_records_a_sha256_by_gateway_or_node_id():
    got = nodes.parse({"nodes": [{"name": "n", "api_base": "http://h.invalid:1/v1", "engine": "llama-server",
                                  "models": [{"id": "G", "as": "N", "sha256": SHA.upper()}, "Other"]}]})[0]
    assert got.sha256("G") == got.sha256("N") == SHA and got.sha256("Other") == ""
    assert got.node_id("G") == "N" and got.models == ("G", "Other")


def test_a_malformed_sha256_is_refused():
    with pytest.raises(ValueError, match="sha256"):
        nodes.parse({"nodes": [{"name": "n", "api_base": "http://h.invalid:1/v1", "engine": "llama-server",
                                "models": [{"id": "G", "sha256": "abc"}]}]})


def test_the_digest_command_prints_the_models_line(tmp_path, monkeypatch, local):
    want = identity.file_digest(local / "gguf" / f"{MODEL}.gguf")
    assert nodes.digest_lines([MODEL]) == [f"- {{id: {MODEL}, sha256: {want}}}"]
    parsed = yaml.safe_load(nodes.digest_lines([str(local / "gguf" / f"{MODEL}.gguf")])[0])
    assert parsed == [{"id": MODEL, "sha256": want}]
