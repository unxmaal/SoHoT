"""A second serving node behind the gateway, with fallback to this machine's copy. #684, #722."""
import asyncio
import importlib.util
import re
import socket
import threading
import time
from pathlib import Path

import pytest
import yaml

from harness import gateway, nodes

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_684", REPO / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

BASE = """model_list:
  - model_name: Qwen2.5-7B-Instruct-Q4_K_M
    engine: llama-server
    litellm_params: &q7
      model: openai/Qwen2.5-7B-Instruct-Q4_K_M
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: mlx-community/Qwen2.5-7B-Instruct-4bit
    litellm_params:
      model: openai/mlx-community/Qwen2.5-7B-Instruct-4bit
      api_base: http://127.0.0.1:8081/v1
      api_key: not-needed
  - model_name: eval-7b
    deprecated_for: Qwen2.5-7B-Instruct-Q4_K_M
    litellm_params: *q7
"""


PC = "PC1/Windows/x86_64/abc123"


def node(**kw):
    raw = {"name": "pc", "api_base": "http://node.invalid:18082/v1", "engine": "llama-server",
           "models": ["Qwen2.5-7B-Instruct-Q4_K_M"], "key": "keychain:svc/acct"}
    raw.update(kw)
    return nodes.parse({"nodes": [raw]})


def config(tmp_path, monkeypatch, nodes_list, text=BASE):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(text, encoding="utf-8")
    out = gateway.write_served(cfg, defaults={}, nodes=nodes_list)
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    return yaml.safe_load(out.read_text(encoding="utf-8")), out


def by_name(data):
    return {e["model_name"]: e for e in data["model_list"]}


def test_no_node_file_means_no_nodes():
    assert nodes.load() == []


def test_the_node_list_is_read_from_this_machines_home(tmp_path, monkeypatch):
    from harness import paths
    (paths.home() / "nodes.yaml").write_text(
        "nodes:\n  - name: pc\n    api_base: http://h.invalid:1/v1\n    engine: llama-server\n"
        "    models: [m]\n", encoding="utf-8")
    assert [n.name for n in nodes.load()] == ["pc"]


@pytest.mark.parametrize("bad, field", [
    ({"name": "PC one"}, "name"), ({"api_base": "node:18082"}, "api_base"),
    ({"engine": "warp"}, "engine"), ({"models": []}, "models"),
    ({"key": "sk-0123456789"}, "key"), ({"timeout": 0}, "timeout"),
    ({"connect_timeout": "soon"}, "connect_timeout")])
def test_a_malformed_node_names_the_field(bad, field):
    with pytest.raises(ValueError, match=field):
        node(**bad)


def test_the_committed_example_parses_and_names_no_host_or_secret():
    path = REPO / "gateway" / "nodes.example.yaml"
    text = path.read_text(encoding="utf-8")
    got = nodes.load(path)
    assert got and got[0].key.startswith("keychain:")
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b|\.local\b|/Users/|/home/", text)
    assert "NODE_HOST" in text


def test_a_node_model_goes_to_the_node_first_and_falls_back_to_this_machines_copy(
        tmp_path, monkeypatch):
    data, _ = config(tmp_path, monkeypatch, node())
    got = by_name(data)
    first = got["Qwen2.5-7B-Instruct-Q4_K_M"]
    assert first["litellm_params"]["api_base"] == "http://node.invalid:18082/v1"
    assert first["litellm_params"]["timeout"] == nodes.TIMEOUT_S
    assert first["litellm_params"]["max_retries"] == 0
    assert first["litellm_params"]["api_key"] == "os.environ/SOHOT_NODE_PC_KEY"
    assert first["engine"] == "llama-server" and first["node"] == "pc"
    assert first["model_info"]["cooldown_time"] == nodes.COOLDOWN_S
    assert first["model_info"]["allowed_fails_policy"]["TimeoutErrorAllowedFails"] == 0
    twin = got["Qwen2.5-7B-Instruct-Q4_K_M@local"]
    assert twin["litellm_params"]["api_base"] == "http://127.0.0.1:8082/v1"
    assert twin["fallback_for"] == "Qwen2.5-7B-Instruct-Q4_K_M"
    assert {"Qwen2.5-7B-Instruct-Q4_K_M": ["Qwen2.5-7B-Instruct-Q4_K_M@local"]} \
        in data["router_settings"]["fallbacks"]


def test_an_old_nickname_for_the_model_goes_to_the_node_too(tmp_path, monkeypatch):
    got = by_name(config(tmp_path, monkeypatch, node())[0])
    assert got["eval-7b"]["node"] == "pc"
    assert "deprecated_for" not in got["eval-7b@local"]


def test_a_lane_alias_adopting_the_model_goes_to_the_node(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    got = by_name(gateway.served(cfg, defaults={"claims": "Qwen2.5-7B-Instruct-Q4_K_M"},
                                 nodes=node()))
    assert got["sohot-claims"]["node"] == "pc"
    assert got["sohot-claims@local"]["litellm_params"]["api_base"].startswith("http://127.0.0.1")


def test_a_node_on_another_engine_does_not_take_the_entry(tmp_path, monkeypatch):
    got = by_name(config(tmp_path, monkeypatch, node(engine="mlx_lm.server"))[0])
    assert "node" not in got["Qwen2.5-7B-Instruct-Q4_K_M"]
    assert "Qwen2.5-7B-Instruct-Q4_K_M@local" not in got


def test_an_mlx_model_the_node_does_not_hold_stays_here(tmp_path, monkeypatch):
    got = by_name(config(tmp_path, monkeypatch, node())[0])
    assert "node" not in got["mlx-community/Qwen2.5-7B-Instruct-4bit"]


def test_the_served_config_never_holds_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SOHOT_NODE_PC_KEY", "sk-very-secret")
    _, out = config(tmp_path, monkeypatch, node())
    assert "sk-very-secret" not in out.read_text(encoding="utf-8")


def test_keys_come_from_the_environment_then_the_keychain():
    n = node()[0]
    asked = []
    look = lambda s, a: asked.append((s, a)) or "from-keychain"  # noqa: E731
    assert nodes.secret(n, {"SOHOT_NODE_PC_KEY": "from-env"}, look) == "from-env"
    assert nodes.secret(n, {}, look) == "from-keychain" and asked == [("svc", "acct")]
    assert nodes.exports([n], {}, look) == ["export SOHOT_NODE_PC_KEY=from-keychain"]
    env = node(key="env:MY_NODE_KEY")[0]
    assert env.key_var == "MY_NODE_KEY" and nodes.exports([env], {}, look) == []


def test_the_schema_guard_still_enforces_on_both_the_node_and_the_fallback(tmp_path, monkeypatch):
    from harness import serving
    _, out = config(tmp_path, monkeypatch, node())
    for name in ("Qwen2.5-7B-Instruct-Q4_K_M", "Qwen2.5-7B-Instruct-Q4_K_M@local", "eval-7b"):
        assert serving.engine_for(name, config=out) == serving.LLAMACPP, name


class Response:
    def __init__(self, base):
        self._hidden_params = {"api_base": base}


def headers(data, base=None):
    return asyncio.run(served.proxy_handler_instance.async_post_call_response_headers_hook(
        data=data, user_api_key_dict=None, response=Response(base) if base else None))


def test_a_reply_from_the_node_names_the_node(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, node(machine="PC1/Windows/x86_64/abc123"))
    got = headers({"model": "eval-7b"}, "http://node.invalid:18082/v1")
    assert got["x-sohot-node"] == "pc"
    assert got["x-sohot-machine"] == "PC1/Windows/x86_64/abc123"
    assert got["x-sohot-model"] == "Qwen2.5-7B-Instruct-Q4_K_M"
    assert got["x-sohot-served-as"] == "eval-7b@pc"
    assert "x-sohot-fallback" not in got


def test_a_node_with_no_fingerprint_is_named_node_colon_name(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, node())
    got = headers({"model": "Qwen2.5-7B-Instruct-Q4_K_M"}, "http://node.invalid:18082/v1")
    assert got["x-sohot-machine"] == "node:pc"
    assert got["x-sohot-served-as"] == "Qwen2.5-7B-Instruct-Q4_K_M@pc"


@pytest.mark.parametrize("sent", ["Qwen2.5-7B-Instruct-Q4_K_M", "Qwen2.5-7B-Instruct-Q4_K_M@local"])
def test_a_fallback_reply_names_this_machine_and_the_node_it_skipped(tmp_path, monkeypatch, sent):
    config(tmp_path, monkeypatch, node())
    monkeypatch.setattr(served, "this_machine", lambda: "Mac/macOS/arm64/here")
    got = headers({"model": sent}, "http://127.0.0.1:8082/v1")
    assert got["x-sohot-machine"] == "Mac/macOS/arm64/here"
    assert got["x-sohot-fallback"] == "pc"
    assert "x-sohot-node" not in got and "x-sohot-served-as" not in got
    assert got["x-sohot-model"] == "Qwen2.5-7B-Instruct-Q4_K_M"


def _refused_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _pre(model):
    data = {"model": model}
    return asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion"))


@pytest.fixture(autouse=True)
def _fresh_reach():
    served._REACH.clear()
    served._REACHING.clear()
    yield


def test_a_refused_node_is_skipped_for_this_machines_copy(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, node(api_base=f"http://127.0.0.1:{_refused_port()}/v1"))
    assert _pre("eval-7b")["model"] == "eval-7b@local"


def test_a_node_that_never_completes_a_connection_is_skipped_within_the_connect_timeout(
        tmp_path, monkeypatch):
    dialled, waits = [], []
    real_wait = asyncio.wait_for

    async def silent(host, port, **kw):
        dialled.append(port)
        await asyncio.sleep(3600)

    async def wait_for(aw, timeout):
        waits.append(timeout)
        return await real_wait(aw, timeout)
    monkeypatch.setattr(asyncio, "open_connection", silent)
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    config(tmp_path, monkeypatch, node(connect_timeout=1))
    got = _pre("Qwen2.5-7B-Instruct-Q4_K_M")["model"]
    assert got == "Qwen2.5-7B-Instruct-Q4_K_M@local"
    assert len(dialled) == 1 and waits == [1.0], "the silent dial was not given up at the node's connect timeout"
    assert _pre("eval-7b")["model"] == "eval-7b@local"
    assert len(dialled) == 1, "a node found silent was dialled again inside its cooldown"


def test_a_reachable_node_keeps_the_request_and_is_asked_once_per_window(tmp_path, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    accepted = []
    def accept():
        try:
            while True:
                accepted.append(s.accept())
        except OSError:
            return
    threading.Thread(target=accept, daemon=True).start()
    try:
        config(tmp_path, monkeypatch, node(api_base=f"http://127.0.0.1:{s.getsockname()[1]}/v1"))
        assert _pre("eval-7b")["model"] == "eval-7b"
        assert _pre("Qwen2.5-7B-Instruct-Q4_K_M")["model"] == "Qwen2.5-7B-Instruct-Q4_K_M"
        time.sleep(0.2)
        assert len(accepted) == 1
    finally:
        s.close()


def test_a_name_with_no_node_is_never_probed(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch, node())
    assert _pre("mlx-community/Qwen2.5-7B-Instruct-4bit")["model"] == \
        "mlx-community/Qwen2.5-7B-Instruct-4bit"
    assert served._REACH == {}


def test_a_hung_shape_probe_does_not_stall_the_event_loop_or_other_replies(monkeypatch):
    """#722: served_shape's urllib calls ran on the gateway's event loop."""
    from harness import context

    entered, release, left = threading.Event(), threading.Event(), threading.Event()

    def hung(spec, *a, **k):
        entered.set()
        release.wait(10)
        left.set()
        return 4096
    monkeypatch.setattr(context, "served_ctx", hung)
    monkeypatch.setattr(context, "served_slots", hung)
    served._SHAPES.clear()
    served._PROBING.clear()

    async def both():
        done, during = [], []

        async def ticker():
            while not done:
                await asyncio.sleep(0.01)
                if entered.is_set() and not left.is_set():
                    during.append(1)

        async def replies():
            got = await asyncio.gather(served.shape("slow-a"), served.shape("slow-b"))
            done.append(1)
            release.set()
            return got
        _, (a, b) = await asyncio.gather(ticker(), replies())
        return len(during), a, b
    ticked, a, b = asyncio.run(both())
    served._SHAPES.clear()
    # Replies came back while the probe was still hung, and the loop kept ticking under it.
    assert a == {} and b == {}
    assert ticked > 0


def test_a_node_reports_its_shape_from_props_with_its_key(tmp_path, monkeypatch):
    from harness import context
    config(tmp_path, monkeypatch, node())
    monkeypatch.setenv("SOHOT_NODE_PC_KEY", "k1")
    seen = []

    def get(url, key=""):
        seen.append((url, key))
        if url.endswith("/props"):
            return {"total_slots": 8, "default_generation_settings": {"n_ctx": 32768}}
        return {"data": [{"id": "Qwen2.5-7B-Instruct-Q4_K_M"}]}
    monkeypatch.setattr(context, "_get_json", get)
    assert context.served_ctx("Qwen2.5-7B-Instruct-Q4_K_M") == 32768
    assert context.served_slots("Qwen2.5-7B-Instruct-Q4_K_M") == 8
    assert {k for _, k in seen} == {"k1"}
    assert all(u.startswith("http://node.invalid:18082/") for u, _ in seen)


def test_a_run_served_partly_by_a_node_and_partly_here_is_filed_as_several_hosts():
    from evals import run
    seen = {("http://127.0.0.1:4000", "eval-7b"): {"machine": "here",
                                                    "machines": ["here", "node:pc"]}}
    got, away = run.serving_machine(seen, "here")
    assert away and got.startswith("unknown: several hosts served")
    assert "node:pc" in got


def test_a_run_the_node_served_whole_is_filed_under_the_node():
    from evals import run
    seen = {("http://127.0.0.1:4000", "eval-7b"): {"machine": "node:pc", "machines": ["node:pc"]}}
    assert run.serving_machine(seen, "here") == ("node:pc", True)


def test_replies_accumulate_every_host_that_answered(monkeypatch):
    from harness import completion
    monkeypatch.setattr(completion, "SERVED", {})

    class R:
        status_code = 200

        def __init__(self, who):
            self.headers = {"x-sohot-machine": who, "x-sohot-model": "m"}
    completion._note("http://g", "eval-7b", R("node:pc"))
    completion._note("http://g", "eval-7b", R("here"))
    assert completion.SERVED[("http://g", "eval-7b")]["machines"] == ["here", "node:pc"]


def test_comparable_refuses_a_node_run_beside_a_run_here():
    from evals.core import Receipt, comparable
    base = dict(modality="claims", case_ids=("a",), repeat=1, sampling={}, gateway="g")
    ok, why = comparable(Receipt(**base, machine="node:pc"),
                         Receipt(**base, machine="Mac/macOS/arm64/here"))
    assert not ok and "serving machine" in why


def test_smoke_passes_up_on_the_node_and_down_on_a_fast_fallback():
    n = nodes.parse({"nodes": [{"name": "pc", "api_base": "http://h.invalid:1/v1",
                                "engine": "llama-server", "models": ["m"], "machine": PC}]})

    class R:
        status_code = 200

        def __init__(self, h):
            self.headers = h
    up = nodes.smoke("g", "k", n, get=lambda url, node: (200, {"m"}),
                     ask=lambda *a: R({"x-sohot-node": "pc", "x-sohot-machine": PC}))
    assert up == [(True, "node pc up: m served by pc")]
    down = nodes.smoke("g", "k", n, get=lambda url, node: (_ for _ in ()).throw(OSError("no")),
                       ask=lambda *a: R({"x-sohot-fallback": "pc"}))
    assert down[0][0] and "fell back" in down[0][1]
    wrong = nodes.smoke("g", "k", n, get=lambda url, node: (200, {"m"}),
                        ask=lambda *a: R({"x-sohot-fallback": "pc"}))
    assert not wrong[0][0]


def test_a_node_forces_ipv4_for_the_gateway_and_its_probe(tmp_path, monkeypatch):
    """A .local name can resolve to a link-local IPv6 address first that never connects."""
    data, _ = config(tmp_path, monkeypatch, node())
    assert data["litellm_settings"]["force_ipv4"] is True
    assert by_name(data)["Qwen2.5-7B-Instruct-Q4_K_M"]["ipv4"] is True
    asked = []

    async def fake(host, port, **kw):
        asked.append(kw)
        raise OSError("no")
    monkeypatch.setattr(asyncio, "open_connection", fake)
    _pre("eval-7b")
    assert asked == [{"family": socket.AF_INET}]


def test_a_node_may_opt_out_of_ipv4(tmp_path, monkeypatch):
    data, _ = config(tmp_path, monkeypatch, node(ipv4=False))
    assert "force_ipv4" not in (data.get("litellm_settings") or {})


def test_a_malformed_node_list_keeps_the_lane_aliases_and_says_why(tmp_path, capsys):
    from harness import paths
    (paths.home() / "nodes.yaml").write_text("nodes:\n  - name: pc\n", encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    got = by_name(gateway.served(cfg, defaults={"claims": "Qwen2.5-7B-Instruct-Q4_K_M"}))
    assert "sohot-claims" in got and "node" not in got["sohot-claims"]
    assert "serving without nodes" in capsys.readouterr().err


def test_a_node_that_advertises_another_id_is_sent_that_id(tmp_path, monkeypatch):
    """A router-mode node names a model by its models-dir stem, which need not be the gateway's id."""
    n = node(models=[{"id": "Qwen2.5-7B-Instruct-Q4_K_M", "as": "qwen2.5-7b-instruct-q4_k_m"}])
    got = by_name(config(tmp_path, monkeypatch, n)[0])
    assert got["Qwen2.5-7B-Instruct-Q4_K_M"]["litellm_params"]["model"] == \
        "openai/qwen2.5-7b-instruct-q4_k_m"
    assert got["eval-7b"]["litellm_params"]["model"] == "openai/qwen2.5-7b-instruct-q4_k_m"
    assert got["Qwen2.5-7B-Instruct-Q4_K_M@local"]["litellm_params"]["model"] == \
        "openai/Qwen2.5-7B-Instruct-Q4_K_M"


def test_headers_name_what_each_side_serves_when_the_ids_differ(tmp_path, monkeypatch):
    n = node(models=[{"id": "Qwen2.5-7B-Instruct-Q4_K_M", "as": "qwen2.5-7b-instruct-q4_k_m"}])
    config(tmp_path, monkeypatch, n)
    up = headers({"model": "Qwen2.5-7B-Instruct-Q4_K_M"}, "http://node.invalid:18082/v1")
    assert up["x-sohot-model"] == "qwen2.5-7b-instruct-q4_k_m"
    assert up["x-sohot-served-as"] == "Qwen2.5-7B-Instruct-Q4_K_M@pc"
    down = headers({"model": "Qwen2.5-7B-Instruct-Q4_K_M"}, "http://127.0.0.1:8082/v1")
    assert down["x-sohot-model"] == "Qwen2.5-7B-Instruct-Q4_K_M"
    assert "x-sohot-served-as" not in down


@pytest.mark.parametrize("bad", [[{"id": "m"}], [{"as": "m"}], ["m", 3]])
def test_a_model_entry_must_be_an_id_or_an_id_and_its_node_name(bad):
    with pytest.raises(ValueError, match="models"):
        node(models=bad)


def test_smoke_fails_a_node_that_does_not_advertise_the_id_it_is_sent():
    n = nodes.parse({"nodes": [{"name": "pc", "api_base": "http://h.invalid:1/v1",
                                "engine": "llama-server", "models": [{"id": "M", "as": "m-stem"}],
                                "machine": PC}]})
    got = nodes.smoke("g", "k", n, get=lambda url, node: (200, {"other"}),
                      ask=lambda *a: pytest.fail("asked the gateway"))
    assert got[0][0] is False and "m-stem" in got[0][1] and "other" in got[0][1]


def test_smoke_passes_a_fast_named_refusal_for_a_model_with_no_local_copy():
    """#823: down, with nothing here to fall back to, the right answer is a quick 503 that says so."""
    n = nodes.parse({"nodes": [{"name": "pc", "api_base": "http://h.invalid:1/v1",
                                "engine": "llama-server", "models": ["m"], "machine": PC}]})

    class R:
        headers = {}

        def __init__(self, code, text):
            self.status_code, self.text = code, text
    down = lambda url, node: (_ for _ in ()).throw(OSError("no"))  # noqa: E731
    ok = nodes.smoke("g", "k", n, get=down,
                     ask=lambda *a: R(503, f"node pc is down and {nodes.NO_LOCAL_COPY} m"))
    assert ok[0][0] and "refused" in ok[0][1]
    bare = nodes.smoke("g", "k", n, get=down, ask=lambda *a: R(500, "Connection error"))
    assert not bare[0][0] and "HTTP 500" in bare[0][1]
    ticks = iter([0.0, 60.0])
    slow = nodes.smoke("g", "k", n, get=down, clock=lambda: next(ticks),
                       ask=lambda *a: R(503, f"node pc is down and {nodes.NO_LOCAL_COPY} m"))
    assert not slow[0][0]
