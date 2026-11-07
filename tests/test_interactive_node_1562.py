"""An interactive node: the gateway sends a lane's alias to another machine's interactive server first. #1562."""
import os
import plistlib
import subprocess

import pytest
import yaml

from harness import completion, context, delegate, exclusive, gateway, interactive, nodes, serving
from harness.commands import interactive as interactive_cmd
from tests import shells
from tests.test_interactive_1561 import DECIDE, EXTRACT, URL, _entry, _fake_reply
from tests.test_launchd import GEN, _install

NODE_BASE = "http://styx.invalid:8083/v1"
BASE = f"""model_list:
  - model_name: {DECIDE}
    engine: llama-server
    litellm_params:
      model: openai/{DECIDE}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: {EXTRACT}
    engine: llama-server
    litellm_params: &q7
      model: openai/{EXTRACT}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: eval-7b
    engine: llama-server
    deprecated_for: {EXTRACT}
    litellm_params: *q7
"""


def styx(**kw):
    raw = {"name": "styx", "api_base": NODE_BASE, "engine": "llama-server", "models": [DECIDE, EXTRACT],
           "lanes": ["decide", "extract"], "machine": "Mac14,12/macOS/arm64/abc123"}
    raw.update(kw)
    return nodes.parse({"nodes": [raw]})


@pytest.fixture
def pinned():
    plan = {"url": URL, "budget_bytes": 35 * 1024 ** 3, "bytes": 11 * 1024 ** 3,
            "lanes": {"decide": _entry(DECIDE), "extract": _entry(EXTRACT, 6.0)}, "skipped": {}}
    interactive.write(plan)
    return plan


def serve(tmp_path, monkeypatch, found):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(cfg))
    out = gateway.write_served(cfg, defaults={}, nodes=found)
    return {e["model_name"]: e for e in yaml.safe_load(out.read_text(encoding="utf-8"))["model_list"]}


def test_a_lane_node_takes_only_its_lane_aliases_and_the_eval_router_keeps_its_models(pinned, tmp_path, monkeypatch):
    got = serve(tmp_path, monkeypatch, styx(models=[DECIDE, EXTRACT, "only-on-styx"]))
    assert "only-on-styx" not in got
    for lane, stem in (("decide", DECIDE), ("extract", EXTRACT)):
        alias = f"sohot-{lane}"
        assert got[alias][nodes.NODE_KEY] == "styx" and got[alias]["litellm_params"]["api_base"] == NODE_BASE
        assert got[alias + nodes.LOCAL_SUFFIX]["litellm_params"]["api_base"] == f"{URL}/v1"
        assert got[alias + nodes.LOCAL_SUFFIX]["litellm_params"]["model"] == f"openai/{stem}"
    # Evals and infovore's eval-7b measure and serve on this machine's router, never the node.
    for name in (DECIDE, EXTRACT, "eval-7b"):
        assert nodes.NODE_KEY not in got[name] and got[name]["litellm_params"]["api_base"].endswith(":8082/v1")
        assert name + nodes.LOCAL_SUFFIX not in got


def test_a_node_without_lanes_still_takes_every_entry_for_its_models(pinned, tmp_path, monkeypatch):
    got = serve(tmp_path, monkeypatch, styx(lanes=[]))
    assert got["eval-7b"][nodes.NODE_KEY] == "styx" and got["sohot-decide"][nodes.NODE_KEY] == "styx"


@pytest.mark.parametrize("lanes", [["svg"], "decide", ["decide", "agent"]])
def test_a_lane_the_interactive_server_does_not_pin_is_refused_in_nodes_yaml(lanes):
    with pytest.raises(ValueError, match="lanes"):
        styx(lanes=lanes)


def test_a_delegation_on_a_node_lane_goes_through_the_gateway_and_never_waits_on_the_lock(pinned, tmp_path,
                                                                                          monkeypatch):
    serve(tmp_path, monkeypatch, styx(lanes=["extract", "decide"]))
    monkeypatch.setattr(delegate, "busy", lambda: "adopt job 0241 (Qwen3.6 vs Ornith)")
    monkeypatch.setattr(exclusive, "holder", lambda: {"job": "0241"})
    monkeypatch.setattr(delegate, "loaded", lambda *a, **k: pytest.fail("asked the eval router's residency"))
    counted = []
    monkeypatch.setattr(completion, "token_counter", lambda base, model: counted.append((base, model)) or (lambda t: 1))
    sent = []
    monkeypatch.setattr(completion, "complete_full", _fake_reply(sent))
    monkeypatch.setattr(delegate, "ask", lambda q, s, where, **kw: (
        {"answers": {"answer": "yes"}, "probabilities": {"answer": {"yes": 1.0}}},
        _fake_reply(sent)(q, where.model, where.base, response_format={})))
    got = delegate.complete("extract", "exit code?", max_tokens=8)
    decided = delegate.decide("sky blue?", interactive_cmd.SCHEMA)
    gw = completion.gateway_url()
    assert sent == [(gw, "sohot-extract"), (gw, "sohot-decide")]
    assert got["spec"] == f"llamacpp:{EXTRACT}" and decided["spec"] == f"llamacpp:{DECIDE}"
    # Its budget is counted on this machine's copy, the server a fallback lands on.
    assert set(counted) == {(URL, EXTRACT)}


def test_a_node_lanes_upstream_is_this_machines_copy_and_other_aliases_are_not_pinned(pinned, tmp_path, monkeypatch):
    serve(tmp_path, monkeypatch, styx(lanes=["decide"]))
    gw = completion.gateway_url()
    assert interactive.upstream(serving.Route(gw, "sohot-decide", {})) == (URL, DECIDE)
    assert interactive.upstream(serving.Route(gw, "sohot-extract", {})) is None
    assert interactive.node_route("extract") is None
    monkeypatch.setattr("harness.router.statuses", lambda get=None, base="": {DECIDE: "loaded", EXTRACT: "loaded"})
    assert delegate.route("extract")[1].base == URL


def test_the_gateway_is_not_stale_while_a_node_answers_a_pinned_lane_first(pinned, tmp_path, monkeypatch):
    serve(tmp_path, monkeypatch, styx())
    assert interactive.stale_gateway(pinned) is False
    moved = {**pinned, "url": "http://127.0.0.1:18084"}
    assert interactive.stale_gateway(moved) is True


def _statuses(by_node):
    def get_for(node):
        def get(path):
            got = by_node[node.name]
            if got is None:
                raise OSError("connection refused")
            return {"data": [{"id": k, "status": {"value": v}} for k, v in got.items()]}
        return get
    return get_for


def test_node_health_names_a_node_that_is_up_without_its_model_and_lets_a_down_node_fall_back(pinned, tmp_path,
                                                                                             monkeypatch):
    found = styx()
    serve(tmp_path, monkeypatch, found)
    good = interactive.node_health(get=_statuses({"styx": {DECIDE: "loaded", EXTRACT: "loaded"}}), found=found)
    assert good["decide"] == {"node": "styx", "routed": True, "up": True, "model": DECIDE, "loaded": True}
    assert interactive.node_ok(good)
    half = interactive.node_health(get=_statuses({"styx": {DECIDE: "loaded", EXTRACT: "unloaded"}}), found=found)
    assert not half["extract"]["loaded"] and not interactive.node_ok(half)
    down = interactive.node_health(get=_statuses({"styx": None}), found=found)
    assert not down["decide"]["up"] and interactive.node_ok(down)
    serve(tmp_path, monkeypatch, [])
    unrouted = interactive.node_health(get=_statuses({"styx": {DECIDE: "loaded", EXTRACT: "loaded"}}), found=found)
    assert not unrouted["decide"]["routed"] and not interactive.node_ok(unrouted)


def test_the_probe_names_who_answered_each_call(monkeypatch):
    served = {}
    gw = completion.gateway_url()
    hosts = iter([{"node": "styx"}, {"node": "styx"}, {"fallback": "styx"}, None])

    def decide():
        got = next(hosts)
        if got:
            served[(gw, "sohot-decide")] = {"node": "", "fallback": "", **got}
        return {"spec": "x"}
    got = interactive_cmd.probe(3, decide=decide, complete=lambda: {"spec": "y"}, code=lambda: {"spec": "z"},
                                sample=lambda: None, busy=lambda: "", served=served)
    assert got["lanes"]["decide"]["hosts"] == {"fallback:styx": 1, "here": 1, "styx": 1}
    assert got["lanes"]["extract"]["hosts"] == {"here": 3}


def test_a_reply_records_the_node_or_the_fallback_it_came_through(monkeypatch):
    class R:
        status_code = 200
        headers = {"x-sohot-machine": "Mac15,14/macOS/arm64/x", "x-sohot-fallback": "styx"}
    monkeypatch.setattr(completion, "SERVED", {})
    completion._note("http://127.0.0.1:4000", "sohot-decide", R())
    assert completion.SERVED[("http://127.0.0.1:4000", "sohot-decide")]["fallback"] == "styx"


def test_interactive_lanes_pins_only_those_lanes_and_names_the_rest(monkeypatch, tmp_path):
    monkeypatch.setenv(interactive.LANES_ENV, "extract, decide")
    sized = {"stem": "", "bytes": 1, "ctx": 1, "slots": 1}
    got = interactive.choose({"decide": f"llamacpp:{DECIDE}", "extract": f"llamacpp:{EXTRACT}",
                              "code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}, {}, sized=lambda stem, d, g=None: {
                                  **sized, "stem": stem})
    assert sorted(got["lanes"]) == ["decide", "extract"]
    assert interactive.LANES_ENV in got["skipped"]["code"]
    monkeypatch.setenv(interactive.LANES_ENV, "decide,svg")
    with pytest.raises(ValueError, match="svg"):
        interactive.here()


def test_an_interactive_node_renders_only_the_interactive_unit_listening_with_a_key(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LH_WATCHDOG_") and k != "LH_ROLE"}
    env.update(LH_ROLE="interactive", LOCALHARNESS_HOME=str(tmp_path / "home"), LLAMACPP_HOST="0.0.0.0",
               LLAMACPP_API_KEY_FILE=str(tmp_path / "key"), INTERACTIVE_LANES="decide,extract")
    out = tmp_path / "out"
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(out)], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    units = {p.stem.rsplit(".", 1)[-1]: plistlib.loads(p.read_bytes()) for p in out.glob("*.plist")}
    assert list(units) == ["interactive"]
    got = units["interactive"]["EnvironmentVariables"]
    assert (got["LLAMACPP_HOST"], got["INTERACTIVE_LANES"]) == ("0.0.0.0", "decide,extract")
    assert got["LLAMACPP_API_KEY_FILE"] == str(tmp_path / "key")
    # Kept for a later plain install, like the role itself.
    env = {k: v for k, v in env.items() if k not in ("LH_ROLE", "LLAMACPP_HOST", "INTERACTIVE_LANES")}
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(tmp_path / "again")], capture_output=True,
                          text=True, env=env)
    again = plistlib.loads((tmp_path / "again" / "com.unxmaal.localharness.interactive.plist").read_bytes())
    assert again["EnvironmentVariables"]["LLAMACPP_HOST"] == "0.0.0.0"


def test_a_scheduler_unit_never_listens_on_the_lan_unless_told(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("LH_ROLE", "LLAMACPP_HOST", "LLAMACPP_API_KEY_FILE")}
    env.update(LOCALHARNESS_HOME=str(tmp_path / "home"), LH_ROLE="scheduler")
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(tmp_path / "out")], capture_output=True, text=True,
                          env=env)
    assert proc.returncode == 0, proc.stderr
    unit = plistlib.loads((tmp_path / "out" / "com.unxmaal.localharness.interactive.plist").read_bytes())
    assert "LLAMACPP_HOST" not in unit["EnvironmentVariables"]


def test_an_interactive_node_install_drops_every_other_unit_and_audits_no_store(tmp_path):
    argv, env = _install(tmp_path, role="interactive", run=False)
    (tmp_path / "deploy" / "scripts" / "serve-audit.sh").write_text("echo AUDITED; exit 1\n", encoding="utf-8")
    got = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
    calls = (tmp_path / "state" / "log").read_text(encoding="utf-8").splitlines()
    assert got.returncode == 0, got.stderr[-1500:]
    assert "AUDITED" not in got.stdout
    loaded = [c for c in calls if c.startswith("bootstrap")]
    assert loaded and all(c.endswith(".interactive.plist") for c in loaded), loaded
    for service in ("gateway", "worker", "discover", "watchdog", "mlx"):
        assert f"removed com.unxmaal.localharness.{service} (LH_ROLE=interactive)" in got.stdout
    assert "removed com.unxmaal.localharness.interactive " not in got.stdout
