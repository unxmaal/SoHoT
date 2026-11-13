"""One release's code reading what another release wrote: a schema-ahead job, an older node's report, the deploy's served gateway config. #1792."""
from __future__ import annotations

import json
import types

import pytest

from harness import api_spend, context, engine_smoke, gateway, interactive, models, node_state, nodes, paths
from harness import memory_store as ms
from harness import workqueue as wq
from tests.test_node_digest_stale_1775 import MODEL, node  # noqa: F401
from tests.test_styx_batch_1689 import NODE, STEM, styx  # noqa: F401

#: The report the first node_state release (#1689) wrote: no models.*.file, which #1775 added.
FIRST_REPORT = {"at": 100.0, "level": 1, "alarming": False, "available_gb": 20.0, "ceiling_gb": 28.0,
                "reserve_gb": 4.0, "pinned_gb": 12.3, "room_gb": 11.7, "lock": {}, "interactive": 0,
                "models": {STEM: {"lane": "extract", "ctx": 32768, "slots": 2, "resident": True}}}
FIRST_MODEL_KEYS = {"lane", "ctx", "slots", "resident"}


# VS-7: a job queued from a checkout whose schema is ahead of the live store is refused at add, not at its start.
def test_a_job_from_a_checkout_ahead_of_the_live_store_is_refused_at_add(tmp_path, monkeypatch):
    top = tmp_path / "ahead"
    (top / "harness" / "memory_store").mkdir(parents=True)
    (top / "harness" / "memory_store" / "schema.py").write_text(
        f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n", encoding="utf-8")
    with wq._store() as c:
        monkeypatch.setattr(paths, "is_live", lambda p: True)
        with pytest.raises(ValueError, match=f"not queued: .*schema {ms.SCHEMA_VERSION + 1}, ahead"):
            wq.add(["true"], cwd=str(top), conn=c)
        assert c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 0


# VS-9: the Studio reads a report written by a node still on the first node_state release.
def test_the_studio_admits_by_a_report_from_the_first_node_release(styx):
    ok, why = node_state.admits(NODE, [STEM], read_fn=lambda n: dict(FIRST_REPORT), held_fn=lambda node: "")
    assert ok, why


def test_the_studio_reads_slots_from_a_cached_report_of_the_first_node_release(styx):
    node_state._path(NODE).parent.mkdir(parents=True, exist_ok=True)
    node_state._path(NODE).write_text(json.dumps(FIRST_REPORT), encoding="utf-8")
    assert node_state.cap(NODE, STEM) == 2


def test_a_report_with_no_file_from_a_release_before_1775_never_vouches_for_a_digest(node):  # noqa: F811
    old = {**FIRST_REPORT, "models": {MODEL: {"lane": "extract", "ctx": 32768, "slots": 2, "resident": True}}}
    sha, why = nodes.digest(nodes.load()[0], MODEL, read=lambda n: old)
    assert sha == "" and "a release before #1775" in why


def test_the_node_report_keeps_every_key_the_first_release_wrote(monkeypatch):
    plan = {"url": "http://127.0.0.1:8083", "bytes": 0, "lanes": {"extract": {"stem": STEM, "ctx": 32768, "slots": 2}}}
    monkeypatch.setattr(interactive, "read", lambda: plan)
    answers = {"/models": {"data": [{"id": STEM, "status": {"value": "loaded"}}]}, f"/slots?model={STEM}": []}
    got = node_state.report(get=lambda path: answers[path], sample=lambda: types.SimpleNamespace(level=1, alarming=False))
    assert set(FIRST_REPORT) <= set(got), set(FIRST_REPORT) - set(got)
    assert FIRST_MODEL_KEYS <= set(got["models"][STEM]), FIRST_MODEL_KEYS - set(got["models"][STEM])


# VS-12: a checkout on the live home with no served config of its own reads the one the deploy's gateway serves.
SERVED = """model_list:
  - model_name: sohot-code
    engine: llama-server
    litellm_params:
      model: openai/Deployed-Code
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
BASE = """model_list:
  - model_name: Checkout-Only
    engine: llama-server
    litellm_params:
      model: openai/Checkout-Only
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""


@pytest.fixture
def worktree(tmp_path, monkeypatch):
    """(checkout base config, deploy dir): the deploy has a served config, the checkout has none."""
    deploy = tmp_path / "deploy"
    (deploy / "gateway").mkdir(parents=True)
    (deploy / "gateway" / "config.yaml").write_text(BASE, encoding="utf-8")
    (deploy / "gateway" / "config.served.yaml").write_text(SERVED, encoding="utf-8")
    base = tmp_path / "wt" / "gateway" / "config.yaml"
    base.parent.mkdir(parents=True)
    base.write_text(BASE, encoding="utf-8")
    monkeypatch.delenv(gateway.ENV_VAR, raising=False)
    monkeypatch.setattr(gateway, "DEFAULT", base)
    asked = []
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: asked.append(1) or deploy)
    return base, deploy, asked


def test_a_checkout_on_the_live_home_reads_the_deploys_served_config(worktree, monkeypatch):
    base, deploy, _ = worktree
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    want = deploy / "gateway" / "config.served.yaml"
    assert gateway.serving_path() == want
    assert "sohot-code" in {e["model_name"] for e in models._entries()}
    assert (context._entry_for("sohot-code") or {}).get("litellm_params", {}).get("model") == "openai/Deployed-Code"
    assert api_spend.config_path() == want
    assert "sohot-code" in {e["model_name"] for e in engine_smoke.load()["model_list"]}


def test_a_scratch_home_or_a_named_config_reads_this_checkouts_own(worktree, monkeypatch):
    base, _, asked = worktree
    assert gateway.serving_path() == gateway.served_path()
    assert "sohot-code" not in {e["model_name"] for e in models._entries()}
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    assert gateway.serving_path(base) == gateway.served_path(base)
    assert asked == []


def test_the_deploy_reads_its_own_served_config_without_asking_where_the_deploy_is(worktree, monkeypatch):
    base, _, asked = worktree
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    gateway.served_path().write_text(SERVED, encoding="utf-8")
    assert gateway.serving_path() == gateway.served_path() and asked == []
