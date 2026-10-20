"""A parked node stays in nodes.yaml but out of routing, fallbacks, probes and watchdog checks, and is named. #1061."""
from __future__ import annotations

import time

import pytest
import yaml

from harness import gateway, live_audit, lanprobe, morning, nodes, paths
from harness import memory_store as ms
from harness import watchdog as wd
from harness.commands import morning as morning_cmd

BASE = """model_list:
  - model_name: Qwen2.5-7B-Instruct-Q4_K_M
    engine: llama-server
    litellm_params:
      model: openai/Qwen2.5-7B-Instruct-Q4_K_M
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
NODE = """nodes:
  - name: khryll
    api_base: http://node.invalid:18082/v1
    engine: llama-server
    machine: "PC1/Windows/x86_64/abc123"
    models: [Qwen2.5-7B-Instruct-Q4_K_M, Qwen2.5-14B-Instruct-Q4_K_M]
{extra}"""


def write_nodes(parked: bool | None) -> None:
    extra = "" if parked is None else f"    parked: {'true' if parked else 'false'}\n"
    (paths.home() / "nodes.yaml").write_text(NODE.format(extra=extra), encoding="utf-8")


def test_a_parked_node_is_kept_but_left_out_of_load_and_listed_as_parked():
    write_nodes(True)
    assert nodes.load() == []
    assert [n.name for n in nodes.parked()] == ["khryll"]
    assert nodes.parked_names() == ["khryll"]
    write_nodes(None)
    assert [n.name for n in nodes.load()] == ["khryll"] and nodes.parked() == []


def test_parked_must_be_a_boolean():
    (paths.home() / "nodes.yaml").write_text(NODE.format(extra="    parked: soon\n"), encoding="utf-8")
    with pytest.raises(ValueError, match="parked"):
        nodes.load()
    assert nodes.parked_names() == []


def test_the_gateway_routes_nothing_to_a_parked_node(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    write_nodes(True)
    data = yaml.safe_load(gateway.write_served(cfg, defaults={}).read_text(encoding="utf-8"))
    names = {e["model_name"]: e for e in data["model_list"]}
    assert names["Qwen2.5-7B-Instruct-Q4_K_M"]["litellm_params"]["api_base"] == "http://127.0.0.1:8082/v1"
    assert not any(e.get(nodes.NODE_KEY) for e in data["model_list"])
    assert "Qwen2.5-14B-Instruct-Q4_K_M" not in names
    assert not (data.get("router_settings") or {}).get("fallbacks")


def test_the_lan_probe_and_the_install_check_skip_a_parked_node_and_name_it(capsys):
    write_nodes(True)
    assert lanprobe.targets(nodes.load()) == []
    assert nodes.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "PARK  node khryll is parked" in out and "FAIL" not in out
    assert nodes.main(["smoke", "--gateway", "http://127.0.0.1:1"]) == 0
    out = capsys.readouterr().out
    assert "PARK  node khryll" in out and "SKIP" not in out


def _fallen_back(tmp_path, monkeypatch):
    """A served config from before the park still names khryll, and its requests fell back here."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    write_nodes(False)
    gateway.write_served(cfg, defaults={})
    conn = ms.connect()
    now = time.time()
    for i in range(wd.FALLBACK_MAX + 5):
        conn.execute("INSERT INTO gateway_requests (at, alias) VALUES (?, ?)",
                     (now - 60 - i, "Qwen2.5-7B-Instruct-Q4_K_M" + nodes.LOCAL_SUFFIX))
    conn.commit()
    return conn


def test_the_watchdog_finds_no_node_fallbacks_for_a_parked_node(tmp_path, monkeypatch):
    conn = _fallen_back(tmp_path, monkeypatch)
    before = live_audit.node_fallbacks(conn)
    assert [f["node"] for f in before] == ["khryll"]
    assert [f.criterion for f in wd._node_fallbacks(wd.World(now=0, fallbacks=before))] == ["node_fallbacks"]
    write_nodes(True)
    after = live_audit.node_fallbacks(conn)
    assert after == []
    assert wd._node_fallbacks(wd.World(now=0, fallbacks=after)) == []


def test_soh_morning_names_the_parked_node():
    write_nodes(True)
    conn = ms.connect()
    r = morning.gather(conn, time.time(), time.time() - 3600, gh=lambda a: "[]", lanes=lambda c: [],
                       stalls=lambda c: [], parked=morning.parked_nodes)
    assert r["parked"] == ["khryll"]
    assert "nodes     khryll parked" in morning_cmd.render(r)
    assert not any("khryll" in n for n in r["needs"])
