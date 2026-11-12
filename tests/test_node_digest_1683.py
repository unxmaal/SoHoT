"""A node-served model's GGUF sha256 comes from the node's own /v1/models tags, recorded by the Studio. #1683."""
import json
import re
from pathlib import Path

import pytest
import yaml

from harness import context, gateway, identity, node_state, nodes

MODEL = "Stem"
NODE_BASE = "http://node1.invalid:8083"
AWAY = "Mac14,12/macOS/arm64/0000000000a1"
SHA = "a" * 64
OTHER = "b" * 64
BASE = f"""model_list:
  - model_name: {MODEL}
    engine: llama-server
    litellm_params:
      model: openai/{MODEL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
PROPS = {"build_info": "b12110-cd959bae9", "chat_template": "{{ messages }}",
         "default_generation_settings": {"n_ctx": 32768, "params": {"temperature": 0.8}}}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(sha="", machine=AWAY):
        entry = {"id": MODEL, "sha256": sha} if sha else MODEL
        raw = {"nodes": [{"name": "node1", "api_base": f"{NODE_BASE}/v1", "engine": "llama-server",
                          "models": [entry], "machine": machine}]}
        path = tmp_path / "nodes.yaml"
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        monkeypatch.setenv(nodes.ENV_VAR, str(path))
        cfg = tmp_path / "config.yaml"
        cfg.write_text(BASE, encoding="utf-8")
        gateway.write_served(cfg, nodes=nodes.load())
        monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
        monkeypatch.setattr(context, "_get_json", lambda url, key="": dict(PROPS))
        monkeypatch.setattr(node_state, "read", lambda node: {
            "models": {MODEL: {"file": {"size": 7, "mtime_ns": 1, "sha256": SHA}}}})
        return nodes.load()
    return make


def _answers(tags):
    return lambda url, node, timeout=None: (200, {MODEL: tuple(tags)})


def _silent(url, node, timeout=None):
    raise OSError("connect refused")


def test_a_digest_the_node_reports_is_recorded_and_the_next_identity_carries_it(setup, monkeypatch, capsys):
    setup()
    assert identity.served(MODEL).get("unresolved"), "no digest before the node is read"
    monkeypatch.setattr(nodes, "_get_models", _answers(["other", f"sha256:{SHA.upper()}"]))
    assert nodes.main(["check"]) == 0
    assert f"PASS  node node1 {MODEL}: sha256 {SHA} reported, recorded in" in capsys.readouterr().out
    assert yaml.safe_load(nodes.path().read_text(encoding="utf-8"))["nodes"][0]["models"] == [MODEL], "nodes.yaml is the owner's"
    assert json.loads(nodes.record_path().read_text(encoding="utf-8"))["node1"]["models"] == {
        MODEL: {"sha256": SHA, "size": 7, "mtime_ns": 1}}
    got = identity.served(MODEL)
    assert "unresolved" not in got, got
    assert got["model"] == {MODEL: SHA}


@pytest.mark.parametrize("cmd", ["check", "smoke"])
def test_a_nodes_yaml_sha256_the_node_contradicts_fails_naming_both(setup, monkeypatch, capsys, cmd):
    setup(sha=OTHER)
    monkeypatch.setattr(nodes, "_get_models", _answers([f"sha256:{SHA}"]))
    monkeypatch.setattr(nodes, "smoke", lambda *a, **k: [(True, "node node1 up")])
    monkeypatch.setattr(nodes, "builds", lambda *a, **k: [])
    argv = ["smoke", "--gateway", "http://127.0.0.1:4000"] if cmd == "smoke" else ["check"]
    assert nodes.main(argv) == 1
    out = capsys.readouterr().out
    assert "FAIL  node node1" in out and OTHER in out and SHA in out
    got = identity.served(MODEL)
    assert "model" not in got and any(OTHER in u and SHA in u for u in got["unresolved"]), got


def test_a_matching_sha256_passes(setup, monkeypatch, capsys):
    setup(sha=SHA)
    monkeypatch.setattr(nodes, "_get_models", _answers([f"sha256:{SHA}"]))
    assert nodes.main(["check"]) == 0
    assert f"sha256 {SHA} matches" in capsys.readouterr().out
    assert identity.served(MODEL)["model"] == {MODEL: SHA}


def test_a_node_that_does_not_answer_leaves_no_digest_and_says_why(setup, monkeypatch, capsys):
    setup()
    monkeypatch.setattr(nodes, "_get_models", _silent)
    assert nodes.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "WARN  node node1 did not answer /v1/models (no answer (OSError))" in out
    assert not nodes.record_path().exists()
    got = identity.served(MODEL)
    assert "model" not in got and any("reported none" in u for u in got["unresolved"]), got


def test_an_answering_node_with_no_tag_drops_what_it_reported_before(setup, monkeypatch, capsys):
    setup()
    monkeypatch.setattr(nodes, "_get_models", _answers([f"sha256:{SHA}"]))
    nodes.main(["check"])
    monkeypatch.setattr(nodes, "_get_models", _answers([]))
    assert nodes.main(["check"]) == 0
    assert f"WARN  node node1 reports no sha256 for {MODEL}" in capsys.readouterr().out
    assert nodes.recorded(nodes.load()[0], MODEL) == ""


def test_a_record_from_another_machine_under_the_same_name_is_not_used(setup, monkeypatch):
    setup()
    monkeypatch.setattr(nodes, "_get_models", _answers([f"sha256:{SHA}"]))
    nodes.main(["check"])
    node = setup(machine="Mac16,1/macOS/arm64/0000000000c3")[0]
    assert nodes.recorded(node, MODEL) == ""


@pytest.mark.parametrize("host, knows, tagged", [
    ("0.0.0.0", True, True), ("127.0.0.1", True, False), ("", True, False), ("0.0.0.0", False, False)])
def test_a_lan_node_preset_tags_the_sha256_of_the_file_it_serves(tmp_path, host, knows, tagged):
    gguf = tmp_path / "real.gguf"
    gguf.write_bytes(b"weights")
    (tmp_path / f"{MODEL}.gguf").symlink_to(gguf)
    rows = [{"stem": MODEL, "path": str(tmp_path / f"{MODEL}.gguf"), "ctx": 4096, "slots": 1, "why": "pinned"}]
    got = nodes.tag_digests(rows, environ={"LLAMACPP_HOST": host}, knows=lambda: knows)
    text = context.preset_text(got, 4096, 1)
    want = f"tags = sha256:{identity.file_digest(gguf)}"
    assert (want in text) is tagged, text


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:LLAMACPP_HOST")
def test_the_host_the_preset_reads_is_the_one_the_node_server_binds():
    from harness import serving
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    serve = (scripts / "serve-llamacpp.sh").read_text(encoding="utf-8")
    assert 'HOST="${LLAMACPP_HOST:-127.0.0.1}"' in serve and not nodes.lan_bound({})
    loopback = re.search(r"^\s*([^\s)]+)\) ;;$", serve, re.M).group(1).split("|")
    assert sorted(loopback) == sorted(serving.LOOPBACK)
    assert all(not nodes.lan_bound({"LLAMACPP_HOST": h}) for h in (*loopback, "[::1]"))
    assert re.search(r"interactive\) vars=\"[^\"]*\bLLAMACPP_HOST\b",
                     (scripts / "launchd.sh").read_text(encoding="utf-8"))
    assert 'export LLAMACPP_HOST="$host"' in (scripts / "services.sh").read_text(encoding="utf-8")


@pytest.mark.parametrize("writer", ["interactive", "router"])
def test_both_preset_writers_tag_on_a_lan_node(tmp_path, monkeypatch, writer):
    from harness import interactive
    gguf = tmp_path / f"{MODEL}.gguf"
    gguf.write_bytes(b"weights")
    monkeypatch.setenv("LLAMACPP_HOST", "0.0.0.0")
    monkeypatch.setattr(nodes, "_knows_tags", lambda: True)
    out = tmp_path / "preset.ini"
    if writer == "interactive":
        interactive.preset(out, {"lanes": {"decide": {"stem": MODEL, "path": str(gguf), "ctx": 4096, "slots": 1,
                                                      "bytes": 7}}})
    else:
        row = {"stem": MODEL, "path": str(gguf), "ctx": 4096, "slots": 1, "why": "planned"}
        monkeypatch.setattr(context, "plan_router", lambda conn, slots, cache: ([row], 1))
        assert context.main([str(out)]) == 0
    assert f"tags = sha256:{identity.file_digest(gguf)}" in out.read_text(encoding="utf-8")
