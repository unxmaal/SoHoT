"""A recorded node digest names the file it was hashed from; a file changed under the same name has no identity. #1775."""
import json

import pytest
import yaml

from harness import context, gateway, identity, node_state, nodes

MODEL = "Stem"
NODE_BASE = "http://node1.invalid:8083"
AWAY = "Mac14,12/macOS/arm64/0000000000a1"
OLD, NEW = "a" * 64, "b" * 64
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
def node(tmp_path, monkeypatch):
    """node1 serving MODEL; returns the dict its live report's file is read from."""
    raw = {"nodes": [{"name": "node1", "api_base": f"{NODE_BASE}/v1", "engine": "llama-server",
                      "models": [MODEL], "machine": AWAY}]}
    (tmp_path / "nodes.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(nodes.ENV_VAR, str(tmp_path / "nodes.yaml"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    gateway.write_served(cfg, nodes=nodes.load())
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    monkeypatch.setattr(context, "_get_json", lambda url, key="": dict(PROPS))
    monkeypatch.setattr(nodes, "_get_models", lambda url, n, timeout=None: (200, {MODEL: (f"sha256:{OLD}",)}))
    live = {"size": 100, "mtime_ns": 1, "sha256": OLD}
    monkeypatch.setattr(node_state, "read", lambda n: {"models": {MODEL: {"file": dict(live)}}})
    assert nodes.main(["check"]) == 0
    assert identity.served(MODEL)["model"] == {MODEL: OLD}
    return live


@pytest.mark.parametrize("now, said", [
    ({"size": 200, "mtime_ns": 2, "sha256": ""}, "has not hashed it"),
    ({"size": 100, "mtime_ns": 2, "sha256": ""}, "has not hashed it"),
    ({"size": 200, "mtime_ns": 2, "sha256": NEW}, f"sha256 {NEW}")])
def test_a_file_changed_under_the_same_name_with_no_check_after_has_no_identity(node, now, said):
    node.clear()
    node.update(now)
    got = identity.served(MODEL)
    assert "model" not in got, f"the stale sha256 {OLD} is still the node's identity: {got}"
    assert any(said in u for u in got["unresolved"]), got


def test_the_record_keys_the_sha256_by_the_file_it_was_hashed_from(node):
    rec = json.loads(nodes.record_path().read_text(encoding="utf-8"))["node1"]
    assert rec["models"][MODEL] == {"sha256": OLD, "size": 100, "mtime_ns": 1}
    node["sha256"] = ""
    assert nodes.digest(nodes.load()[0], MODEL) == (OLD, ""), "same size and mtime: the record still names it"


def test_a_node_that_cannot_report_its_file_does_not_vouch_for_the_record(node, monkeypatch):
    monkeypatch.setattr(node_state, "read", lambda n: {"error": "node node1 has no deploy: ssh"})
    sha, why = nodes.digest(nodes.load()[0], MODEL)
    assert sha == "" and "no deploy: ssh" in why


def test_check_warns_when_the_server_tag_is_older_than_the_file(node, capsys):
    node.update(size=200, mtime_ns=2, sha256="")
    capsys.readouterr()
    nodes.main(["check"])
    assert "changed since it was hashed" in capsys.readouterr().out
    assert json.loads(nodes.record_path().read_text(encoding="utf-8"))["node1"]["models"][MODEL] == {"sha256": OLD}


def test_a_record_written_before_1775_is_still_read():
    n = nodes.Node(name="node1", api_base=f"{NODE_BASE}/v1", engine="llama-server", models=(MODEL,), machine=AWAY)
    nodes.record_path().parent.mkdir(parents=True, exist_ok=True)
    nodes.record_path().write_text(json.dumps({"node1": {"machine": n.identity, "models": {MODEL: OLD}}}),
                                   encoding="utf-8")
    assert nodes.recorded(n, MODEL) == OLD


def test_the_node_reports_its_file_now_and_hashes_nothing_to_do_it(tmp_path, monkeypatch):
    gguf = tmp_path / f"{MODEL}.gguf"
    gguf.write_bytes(b"weights v1")
    monkeypatch.setattr(identity, "cache_path", lambda: tmp_path / "digests.json")
    sha = identity.file_digest(gguf)
    got = node_state.served_file(gguf)
    assert got["sha256"] == sha and got["size"] == len(b"weights v1")
    gguf.write_bytes(b"weights v2, requantised")
    monkeypatch.setattr(identity, "_sha256", lambda path: pytest.fail("the report hashed a file"))
    got = node_state.served_file(gguf)
    assert got["sha256"] == "" and got["size"] == len(b"weights v2, requantised")
    assert node_state.served_file(tmp_path / "gone.gguf").get("error")
