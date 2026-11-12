"""A node takes batch work under its own lease and memory gate, admitted by its own report, preempted by its interactive lanes. #1689."""
from __future__ import annotations

import json
import os
import types

import pytest
import yaml

from evals import run as R
from evals import watch
from harness import completion, context, delegate, exclusive, gateway, interactive, item_lease, node_state, nodes, resources
from harness import memory_store as ms
from harness import serve_lease, serving
from harness import workqueue as wq

NODE = "styx"
STEM = "Qwen2.5-7B-Instruct-Q4_K_M"
LOCAL = "Local-4B"
FP = "Mac14,12/macOS/arm64/731b6725bbad"
ALIAS = gateway.LANE_ALIAS.format("extract")
BASE = f"""model_list:
  - model_name: {STEM}
    engine: llama-server
    litellm_params:
      model: openai/{STEM}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: {LOCAL}
    engine: llama-server
    litellm_params:
      model: openai/{LOCAL}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
"""
FINE = {"level": 1, "alarming": False, "lock": {}, "interactive": 0, "room_gb": 6.7,
        "models": {STEM: {"lane": "extract", "ctx": 32768, "slots": 2, "resident": True}}}


def _served(tmp_path, monkeypatch, *, lanes=("extract",), engine="llama-server", models=(STEM,)):
    raw = {"nodes": [{"name": NODE, "api_base": f"http://{NODE}.invalid:8083/v1", "engine": engine,
                      "models": list(models), "machine": FP, "lanes": list(lanes), "deploy": {"ssh": "ops@styx.invalid"}}]}
    path = tmp_path / "nodes.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    monkeypatch.setenv(nodes.ENV_VAR, str(path))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    return gateway.write_served(cfg, defaults={lane: STEM for lane in lanes}, nodes=nodes.load())


@pytest.fixture
def styx(tmp_path, monkeypatch):
    _served(tmp_path, monkeypatch)


def _eval(*candidates) -> list[str]:
    return ["uv", "run", "python", "-m", "evals.run", "--modality", "extract", "--candidates", ",".join(candidates)]


def _args(*candidates):
    return R.queued_args(_eval(*candidates))


# #778: locality is decided per candidate from the gateway's routing.

def test_a_batch_whose_every_candidate_a_node_serves_takes_the_nodes_lock(styx):
    assert R.lock_kind(_args(ALIAS)) == "node-eval"
    assert R.node_of(_args(ALIAS)) == NODE
    assert resources.classify(_eval(ALIAS)) == resources.on(NODE)


def test_a_mixed_batch_and_a_local_one_take_this_machines_lock(styx):
    assert R.lock_kind(_args(ALIAS, LOCAL)) == "eval"
    assert node_state.placed([ALIAS, LOCAL]) == ("", [])
    assert R.lock_kind(_args(LOCAL)) == "eval"
    assert resources.classify(_eval(ALIAS, LOCAL)) == resources.GPU


def test_a_batch_split_across_two_nodes_is_placed_on_neither(monkeypatch):
    monkeypatch.setattr(node_state, "served_by", lambda s, config=None: {"a": (NODE, "x"), "b": ("other", "y")}[s])
    assert node_state.placed(["a", "b"]) == ("", [])
    assert node_state.placed(["a"]) == (NODE, ["x"])


def test_a_node_only_batch_leaves_this_machines_gpu_lease_and_flock_free(styx):
    with exclusive.held("node-eval", node=NODE):
        assert os.environ[exclusive.NODE_HELD_ENV] == NODE
        assert exclusive.gpu_leases() == 0
        assert not exclusive._taken(exclusive.lock_path())
        with exclusive.gpu_now("image") as got:
            assert got, "a local image job runs beside the node's batch"
        c = ms.connect()
        assert [h["resource"] for h in item_lease.live(c)] == [resources.on(NODE)]
        c.close()
    c = ms.connect()
    assert item_lease.live(c) == []
    c.close()


def test_a_local_batch_still_takes_this_machines_gpu_lease(styx):
    with exclusive.held("eval"):
        assert exclusive.gpu_leases() == 1


def test_a_second_node_batch_waits_for_the_first(styx):
    c = ms.connect()
    first = item_lease.take(c, resources.on(NODE), "job 0001", pid=os.getpid())
    c.close()
    assert first is not None
    assert not wq._free(resources.on(NODE), {})
    assert wq._free(resources.GPU, {})


def test_a_job_naming_a_node_must_be_one_that_node_serves(styx):
    with pytest.raises(ValueError, match="every candidate that node serves"):
        wq.add(_eval(LOCAL), resource=resources.on(NODE))
    assert wq.add(_eval(ALIAS), resource=resources.on(NODE))["resource"] == resources.on(NODE)
    with pytest.raises(ValueError, match="not an unparked node"):
        resources.check(resources.on("nowhere"))


# #713: the node reports its own lock and pressure; the queue admits by it.

def _ssh(rc, out, calls=None):
    def run(argv, script, timeout):
        if calls is not None:
            calls.append(argv[-1])
        return rc, out
    return run


def test_the_studio_reads_the_nodes_report_over_its_deploy_ssh_and_caches_it(styx):
    calls = []
    got = node_state.read(node_state.node(NODE), runner=_ssh(0, "noise\n" + json.dumps(FINE), calls), now=100.0)
    assert got["room_gb"] == 6.7 and calls == ["bash -s -- state ''"]
    again = node_state.read(node_state.node(NODE), runner=_ssh(255, "", calls), now=110.0)
    assert again["room_gb"] == 6.7 and len(calls) == 1
    late = node_state.read(node_state.node(NODE), runner=_ssh(255, "Connection refused", calls), now=200.0)
    assert "did not report" in late["error"] and "Connection refused" in late["error"]


@pytest.mark.parametrize("change,why", [
    ({"alarming": True, "level": 2}, "memory pressure level 2"),
    ({"interactive": 1}, "answering 1 interactive"),
    ({"interactive": None}, "did not say"),
    ({"lock": {"kind": "eval", "pid": 7}}, "own lock is held by eval"),
    ({"models": {STEM: {"resident": False}}}, "does not hold"),
    ({"error": "node styx did not report its state"}, "did not report"),
])
def test_the_node_refuses_batch_work_its_report_says_no_to(styx, change, why):
    ok, said = node_state.admits(NODE, [STEM], read_fn=lambda n: {**FINE, **change}, held_fn=lambda node: "")
    assert not ok and why in said


def test_the_node_admits_batch_work_when_it_is_free(styx):
    assert node_state.admits(NODE, [STEM], read_fn=lambda n: FINE, held_fn=lambda node: "")[0]


def test_the_node_report_names_its_pressure_lock_pinned_set_and_interactive_load(monkeypatch):
    plan = {"url": "http://127.0.0.1:8083", "bytes": 12.3 * node_state.GIB,
            "lanes": {"extract": {"stem": STEM, "ctx": 32768, "slots": 2}}}
    monkeypatch.setattr(interactive, "read", lambda: plan)
    answers = {"/models": {"data": [{"id": STEM, "status": {"value": "loaded"}}]},
               f"/slots?model={STEM}": [{"id": 0, "is_processing": True}, {"id": 1, "is_processing": False}]}
    got = node_state.report(get=lambda path: answers[path], sample=lambda: types.SimpleNamespace(level=1, alarming=False))
    assert got["interactive"] == 1 and got["lock"] == {} and got["pinned_gb"] == 12.3
    assert got["models"][STEM] == {"lane": "extract", "ctx": 32768, "slots": 2, "resident": True, "file": {}}
    assert got["room_gb"] == round(got["ceiling_gb"] - got["reserve_gb"] - 12.3, 2)


# The acceptance: a job that fits styx runs there while the Studio is busy, and interactive work preempts it.

def test_a_job_that_fits_the_node_runs_there_while_the_studios_gpu_is_busy(styx, monkeypatch):
    monkeypatch.setattr(node_state, "read", lambda n, **kw: FINE)
    c = ms.connect()
    studio = item_lease.take(c, resources.GPU, "eval pid busy", pid=os.getpid(), state="eval")
    c.close()
    assert studio is not None
    wq.add(_eval(LOCAL), title="studio")
    wq.add(_eval(ALIAS), title="styx")
    seen = []

    def popen(argv, **kw):
        c = ms.connect()
        seen.append(sorted(h["resource"] for h in item_lease.live(c)))
        c.close()
        return types.SimpleNamespace(returncode=0)
    ran = wq.run_pending(popen=popen)
    assert [j["title"] for j in ran] == ["styx"]
    assert seen == [sorted([resources.GPU, resources.on(NODE)])]
    assert [j["title"] for j in wq.pending()] == ["studio"]


def test_a_node_job_waits_while_the_node_serves_interactive_work(styx, monkeypatch):
    monkeypatch.setattr(node_state, "read", lambda n, **kw: FINE)
    lease = serve_lease.Lease("extract", "a extract delegation", node=NODE)
    lease.serving()
    job = wq.add(_eval(ALIAS), title="styx")
    assert wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=0)) == []
    assert "interactive work comes first" in wq.get(job["id"])["note"]
    lease.drop()


def test_an_interactive_request_on_the_node_preempts_its_batch_between_cases(tmp_path, monkeypatch):
    node_eval = serve_lease.Yielder(tmp_path / "node-run", node=NODE)
    studio_eval = watch.Watch(yielder=serve_lease.Yielder(tmp_path / "studio-run"))
    w = watch.Watch(yielder=node_eval)
    lease = serve_lease.Lease("extract", "a extract delegation", node=NODE)
    lease.serving()
    assert not studio_eval._serve(), "the Studio's eval does not yield to the node's lane"
    monkeypatch.setattr(watch, "sleep", lambda s: lease.drop())
    assert w._serve()
    assert w.yields == 1


def test_a_studio_delegation_never_waits_on_an_eval_the_node_serves():
    pid = os.getppid()
    serve_lease._write(serve_lease._dir("yielders") / f"{pid}.json", {"pid": pid, "state": "case", "node": NODE})
    assert serve_lease.yielders() == []
    assert [r["pid"] for r in serve_lease.yielders(NODE)] == [pid]


def test_a_delegation_to_a_node_lane_takes_the_nodes_serving_lease_at_once(styx, monkeypatch):
    where = serving.Route(serving.bare(completion.gateway_url()), ALIAS, {})
    assert interactive.node_of(where) == NODE
    monkeypatch.setattr(delegate, "_allowance", lambda *a: 60.0)
    with delegate._serving(where, "extract", 64, None, True) as turn:
        assert turn["waited"] == 0.0
        assert serve_lease.held(node=NODE) and not serve_lease.held()


# #762: a router-mode node answers n_ctx 0 on /props; its model's own props say the real shape.

def test_a_router_nodes_context_comes_from_its_models_own_props(tmp_path, monkeypatch):
    _served(tmp_path, monkeypatch, lanes=())
    base = f"http://{NODE}.invalid:8083"
    answers = {f"{base}/models": {"data": [{"id": STEM, "status": {"value": "loaded", "args": []}}]},
               f"{base}/props": {"default_generation_settings": {"n_ctx": 0}, "total_slots": 1},
               f"{base}/props?model={STEM}": {"default_generation_settings": {"n_ctx": 32768}, "total_slots": 2}}
    monkeypatch.setattr(context, "_get_json", lambda url, key="": answers[url])
    assert context.served_ctx(STEM) == 32768
    assert context.served_slots(STEM) == 2


# #754: a node's cap is the one it reports, never this machine's sizing.

def _cap(path) -> dict:
    return {e["model_name"]: (e.get("litellm_params") or {}).get("max_parallel_requests")
            for e in yaml.safe_load(path.read_text(encoding="utf-8"))["model_list"]}


def _report(slots):
    d = node_state._path(NODE).parent
    d.mkdir(parents=True, exist_ok=True)
    node_state._path(NODE).write_text(json.dumps({"models": {STEM: {"slots": slots}}}), encoding="utf-8")


def test_a_routed_mlx_entry_gets_the_nodes_advertised_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "mlx_parallel", lambda repo: 8)
    monkeypatch.setattr(nodes, "_local_engine", lambda entry, data: serving.DEFAULT)
    _report(2)
    assert _cap(_served(tmp_path, monkeypatch, lanes=(), engine=serving.DEFAULT))[STEM] == 2


def test_a_routed_mlx_entry_whose_node_has_not_said_gets_one(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "mlx_parallel", lambda repo: 8)
    monkeypatch.setattr(nodes, "_local_engine", lambda entry, data: serving.DEFAULT)
    assert _cap(_served(tmp_path, monkeypatch, lanes=(), engine=serving.DEFAULT))[STEM] == 1


def test_a_router_node_entry_takes_its_reported_slots(tmp_path, monkeypatch):
    _report(2)
    assert _cap(_served(tmp_path, monkeypatch))[ALIAS] == 2
