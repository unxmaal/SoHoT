"""The served-config readers #1792 left on served_path read the deploy's from a checkout on the live home; a node report missing a key admission reads is refused. #1960."""
from __future__ import annotations

import sqlite3

import pytest

from harness import completion, delegate, interactive, lane_probe, live_audit, node_state, paths, serving
from tests.test_styx_batch_1689 import NODE, STEM, styx  # noqa: F401
from tests.test_vs_inventory_1792 import FIRST_REPORT, SERVED, worktree  # noqa: F401

NODE_SERVED = SERVED + """  - model_name: sohot-decide
    engine: llama-server
    node: styx
    litellm_params:
      model: openai/Node-Decide
      api_base: http://192.0.2.7:8083/v1
      api_key: not-needed
  - model_name: sohot-decide@local
    engine: llama-server
    litellm_params:
      model: openai/Local-Decide
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""


@pytest.fixture
def live(worktree, monkeypatch):  # noqa: F811
    _, deploy, _ = worktree
    served = deploy / "gateway" / "config.served.yaml"
    served.write_text(NODE_SERVED, encoding="utf-8")
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    return served


def _alias(name):
    return serving.Route(completion.gateway_url(), name, {})


def test_delegate_resolves_a_lane_alias_the_deploys_gateway_serves(live):
    assert delegate.upstream(_alias("sohot-code")) == ("http://127.0.0.1:8082", "Deployed-Code")


def test_a_node_lane_is_seen_from_a_checkout_so_its_delegation_takes_the_nodes_lease(live):
    assert "sohot-decide" in interactive._served()
    assert interactive.node_of(_alias("sohot-decide")) == "styx"
    assert interactive.node_route("decide")[1].model == "sohot-decide"


def test_a_stale_pin_in_the_deploys_served_config_is_seen_from_a_checkout(live):
    assert interactive.stale_gateway({"url": "http://127.0.0.1:9999", "lanes": {"code": {"stem": "Pinned-Code"}}})
    assert not interactive.stale_gateway({"url": "http://127.0.0.1:8082", "lanes": {"code": {"stem": "Deployed-Code"}}})


def test_the_lane_probe_asks_the_node_through_the_deploys_served_config(live):
    got = lane_probe._node(_alias("sohot-decide"))
    assert got["config"] == live
    assert delegate.upstream(_alias("sohot-decide"), got["config"]) == ("http://192.0.2.7:8083", "Node-Decide")


def test_the_audit_names_a_nodes_fallbacks_from_a_checkout(live):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE gateway_requests (alias TEXT, at REAL)")
    conn.execute("INSERT INTO gateway_requests VALUES ('sohot-decide@local', 100.0)")
    got = live_audit.node_fallbacks(conn, now=200.0)
    assert [(g["node"], g["aliases"]) for g in got] == [("styx", ["sohot-decide"])]


# VS-9: a key admission judges by that the report lacks vouches for nothing.
@pytest.mark.parametrize("key", ["alarming", "lock"])
def test_a_report_without_a_key_admission_reads_is_refused_naming_it(styx, key):  # noqa: F811
    report = {k: v for k, v in FIRST_REPORT.items() if k != key}
    ok, why = node_state.admits(NODE, [STEM], read_fn=lambda n: dict(report), held_fn=lambda node: "")
    assert not ok and key in why, why
