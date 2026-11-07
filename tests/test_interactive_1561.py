"""The interactive server: pinned lane models apart from the eval router, never waiting on an eval. #1561."""
import re
from pathlib import Path

import pytest

from harness import completion, context, delegate, exclusive, gateway, interactive, memory, paths, router, serving
from harness import watchdog as wd
from harness.commands import interactive as interactive_cmd
from tests.test_context import LLAMA, write_gguf

REPO = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:18083"
GIB = 1024 ** 3
DECIDE = "imajev-4b-Q8_0"
EXTRACT = "Qwen2.5-7B-Instruct-Q4_K_M"


def _entry(stem, gib=5.0, spec=""):
    return {"stem": stem, "path": f"/m/{stem}.gguf", "ctx": 32768, "slots": 2, "weights": 1, "kv": 1,
            "bytes": int(gib * GIB), "spec": spec or f"llamacpp:{stem}", "served": f"llamacpp:{stem}",
            "why": "the lane's model"}


@pytest.fixture
def pinned():
    plan = {"url": URL, "budget_bytes": 25 * GIB, "bytes": 11 * GIB,
            "lanes": {"decide": _entry(DECIDE), "extract": _entry(EXTRACT, 6.0)}, "skipped": {}}
    interactive.write(plan)
    return plan


@pytest.fixture
def held(monkeypatch):
    """The interactive server answers with its pinned models loaded; the eval router holds others."""
    asked = []

    def statuses(get=None, base=""):
        asked.append(base)
        if serving.bare(base) == URL:
            return {DECIDE: "loaded", EXTRACT: "loaded"}
        return {"Ornith-1.5-35B-Q4_K_M": "loaded"}
    monkeypatch.setattr(router, "statuses", statuses)
    return asked


def _fake_reply(sent):
    def complete_full(prompt, model, gateway="", **kw):
        sent.append((serving.bare(gateway), model))
        return completion.Completion(text='{"answer": "A"}' if kw.get("response_format") else "2",
                                     usage={"prompt_tokens": 3, "completion_tokens": 1}, model=model,
                                     timing={"ttft_s": 0.01})
    return complete_full


def test_a_pinned_lane_is_answered_at_once_while_an_eval_holds_the_lock_and_loads_others(pinned, held, monkeypatch):
    monkeypatch.setattr(delegate, "busy", lambda: "adopt job 0241 (Qwen3.6 vs Ornith)")
    monkeypatch.setattr(exclusive, "holder", lambda: {"job": "0241"})
    monkeypatch.setattr(delegate, "loaded", lambda *a, **k: pytest.fail("asked the eval router's residency"))
    counted = []
    monkeypatch.setattr(completion, "token_counter", lambda base, model: counted.append(base) or (lambda t: 1))
    sent = []
    monkeypatch.setattr(completion, "complete_full", _fake_reply(sent))
    monkeypatch.setattr(delegate, "ask", lambda q, s, where, **kw: (
        {"answers": {"answer": "yes"}, "probabilities": {"answer": {"yes": 1.0}}},
        _fake_reply(sent)(q, where.model, where.base, response_format={})))
    got = delegate.complete("extract", "exit code?", max_tokens=8)
    decided = delegate.decide("sky blue?", interactive_cmd.SCHEMA)
    assert sent == [(URL, EXTRACT), (URL, DECIDE)]
    assert got["spec"] == f"llamacpp:{EXTRACT}" and decided["spec"] == f"llamacpp:{DECIDE}"
    assert set(counted) == {URL}
    assert all(serving.bare(b) == URL for b in held)


def test_without_the_interactive_server_the_same_call_is_refused_under_the_lock(held, monkeypatch):
    monkeypatch.setattr(delegate, "busy", lambda: "adopt job 0241")
    monkeypatch.setattr(exclusive, "holder", lambda: {"job": "0241"})
    monkeypatch.setattr(delegate, "loaded", lambda *a, **k: False)
    monkeypatch.setattr(context, "refusal", lambda stem, conn=None: "")
    monkeypatch.setattr(context, "served_ctx", lambda spec, *a, **k: None)
    with pytest.raises(delegate.Refused, match="busy with adopt job 0241"):
        delegate.complete("decide", "x", max_tokens=8, model=f"llamacpp:{DECIDE}")


def test_a_pinned_lane_alias_goes_to_the_interactive_server_and_an_eval_spec_to_the_router(pinned, held,
                                                                                           monkeypatch):
    served = {e["model_name"]: e for e in gateway.served(REPO / "gateway" / "config.yaml", defaults={},
                                                          nodes=[])["model_list"]}
    for lane, stem in (("decide", DECIDE), ("extract", EXTRACT)):
        assert served[f"sohot-{lane}"]["litellm_params"]["api_base"] == f"{URL}/v1"
        assert served[f"sohot-{lane}"]["litellm_params"]["model"] == f"openai/{stem}"
        assert serving.engine_at(URL, data={"model_list": list(served.values())}) == serving.LLAMACPP
    monkeypatch.setattr(context, "refusal", lambda stem, conn=None: "")
    assert serving.route(f"llamacpp:{DECIDE}").base == router.url() == serving.LLAMACPP_URL
    assert delegate.route("decide")[1].base == URL
    assert delegate.route("decide", f"llamacpp:{DECIDE}")[1].base == router.url()


def test_a_lane_whose_model_the_server_does_not_hold_falls_back_to_the_router(pinned, monkeypatch):
    monkeypatch.setattr(router, "statuses", lambda get=None, base="": {DECIDE: "unloaded"})
    monkeypatch.setattr(context, "refusal", lambda stem, conn=None: "")
    assert interactive.route("decide") is None
    assert interactive.route("code") is None


def test_the_install_check_passes_the_ornith_set_on_a_96_gb_studio_and_refuses_only_a_set_that_cannot_fit():
    plan = {"bytes": int(33.6 * GIB), "lanes": {"decide": _entry(DECIDE, 5.7), "extract": _entry(EXTRACT, 6.6),
                                                 "code": _entry("Ornith-1.5-35B-Q4_K_M", 21.3)}}
    ok, why = interactive.check(plan, int(59.8 * GIB), 16 * GIB)
    assert ok and why.startswith("fits: the pinned set 33.6 GiB (decide imajev-4b-Q8_0 5.7, extract "
                                 "Qwen2.5-7B-Instruct-Q4_K_M 6.6, code Ornith-1.5-35B-Q4_K_M 21.3) + 16.0 GiB of MLX "
                                 "beside it = 49.6 GiB of the 59.8 GiB budget; evals get the 10.2 GiB left")
    ok, why = interactive.check(plan, 45 * GIB, 16 * GIB)
    assert not ok and why.endswith("= 49.6 GiB, over the 45.0 GiB budget by 4.6 GiB")


def test_a_refused_check_clears_the_plan_and_install_refuses_the_unit(pinned, monkeypatch):
    monkeypatch.setattr(interactive, "plan_now", lambda **kw: {**pinned, "skipped": {}})
    monkeypatch.setattr(interactive, "check_here", lambda plan: (False, "refused: over by 2.0 GiB"))
    assert interactive.main(["check"]) == 1
    assert interactive.read() == {}
    monkeypatch.setattr(interactive, "check_here", lambda plan: (True, "fits"))
    assert interactive.main(["check"]) == 0 and interactive.read()["lanes"]
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    loop = text.split("install_units() {", 1)[1]
    assert re.search(r'"\$service" = interactive \] && ! \(cd "\$DEPLOY" && uv run python -m harness\.interactive '
                     r'check\)', loop)
    assert "blocked=1" in loop.split('if [ -n "$refused" ]', 1)[1].split("\n  fi\n", 1)[0]


def test_an_eval_candidate_too_big_beside_the_pinned_set_is_refused_at_admission_as_a_harness_limit(
        pinned, tmp_path, monkeypatch):
    from harness import reasons
    write_gguf(tmp_path / "big.gguf", LLAMA)
    monkeypatch.setattr(context, "router_rows", lambda conn: [{"path": str(tmp_path / "big.gguf"), "id": 1}])
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(context, "_weights", lambda path: 12 * GIB)
    why = context.plan(None, budget=20 * GIB, record=False)[0]["why"]
    assert why.startswith("refused: 12.0 GiB of weights over the 9.0 GiB budget")
    assert "11.0 GiB of the machine held by the interactive server's pinned models" in why
    cls = reasons.classify(f"llamacpp:big is not served: {why}", candidate="llamacpp:big")
    assert cls == reasons.PLAN_REFUSED and reasons.CLASSES[cls] == ("declined", reasons.LIMIT)
    monkeypatch.setattr(memory, "available_gb", lambda: 100.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 60.0)
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 55.0)
    ok, said = memory.check_model("org/mlx-big", reserve_gb=0.0)
    assert not ok and said == ("needs 55.0 GB but only 49.0 GB is safely available (100.0 GB free, 60.0 GB GPU "
                               "ceiling, 0.0 GB reserved for the system, 11.0 GB held by the interactive server's "
                               "pinned models)")


def test_the_mlx_coresident_leaves_out_a_lane_the_interactive_server_answers(pinned):
    defaults = {"extract": "mlx-community/Qwen2.5-7B-Instruct-4bit", "svg": "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit"}
    sizes = {"mlx-community/Qwen2.5-7B-Instruct-4bit": 4 * GIB, "mlx-community/Qwen3-30B-A3B-Instruct-2507-4bit": 16 * GIB}
    cfg = REPO / "gateway" / "config.yaml"
    assert context.coresident_bytes(None, defaults, cfg, sizes.get, skip=set()) == 16 * GIB
    only_extract = {"extract": defaults["extract"]}
    assert context.coresident_bytes(None, only_extract, cfg, sizes.get, skip=set()) == 4 * GIB
    assert context.coresident_bytes(None, only_extract, cfg, sizes.get, skip={"extract"}) == 0
    assert context.coresident_bytes(None, only_extract, cfg, sizes.get) == 0


def test_the_install_check_prices_the_mlx_coresident_without_the_lanes_it_is_about_to_pin(monkeypatch):
    monkeypatch.setattr(context, "budget_bytes", lambda conn=None: 60 * GIB)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn, skip=None: 0 if "extract" in skip else 30 * GIB)
    plan = {"bytes": 35 * GIB, "lanes": {"extract": _entry(EXTRACT, 35.0)}}
    assert interactive.check_here(plan)[0]


def _sized(gib):
    return lambda stem, models_dir, got=None: {"stem": stem, "path": f"/m/{stem}.gguf", "ctx": 32768, "slots": 2,
                                               "weights": 1, "kv": 1, "bytes": int(gib[stem] * GIB), "got": got}


NOW = 1_800_000_000.0


def _requests(rows):
    from harness import memory_store as ms
    conn = ms.connect()
    for at, alias, lane, client, purpose, tokens, total in rows:
        conn.execute("INSERT INTO gateway_requests (at, alias, lane, client, purpose, prompt_tokens, completion_tokens, "
                     "total_s) VALUES (?, ?, ?, ?, ?, ?, 0, ?)", (at, alias, lane, client, purpose, tokens, total))
    conn.commit()
    return conn


def test_demand_reads_a_lanes_interactive_requests_their_sizes_and_overlap():
    day = 86400.0
    conn = _requests([
        (NOW - 10, "sohot-decide", "decide", "python-httpx", "work", 800, 5.0),
        (NOW - 8, "imajev-4b-Q8_0", "", "python-httpx", "internal", 3000, 5.0),
        (NOW - 6, "", "decide", "soh-delegate", "work", 8000, 5.0),
        (NOW - 100, "sohot-decide", "decide", "python-httpx", "unknown", 500, 1.0),
        (NOW - 9, "imajev-4b-Q8_0", "", "Python-urllib", "eval", 90000, 5.0),
        (NOW - 9, "eval-7b", "", "Python-urllib", "unknown", 90000, 5.0),
        (NOW - 9, "sohot-code", "code", "python-httpx", "smoke", 90000, 5.0),
        (NOW - 31 * day, "sohot-decide", "decide", "python-httpx", "work", 90000, 5.0)])
    got = interactive.demand(conn, "decide", {"imajev-4b-Q8_0", ""}, now=NOW)
    assert got == {"n": 4, "p99": 3000, "max": 8000, "peak": 3}
    assert interactive.demand(conn, "extract", set(), now=NOW) == {"n": 0, "p99": 0, "max": 0, "peak": 0}


def test_a_pinned_pool_is_sized_from_its_lanes_requests_not_the_eval_plan(tmp_path):
    assert interactive.shape(None, 262144) == (interactive.SLOTS, interactive.POOL_CTX, 0)
    assert interactive.shape({"n": 0}, 16384) == (interactive.SLOTS, 16384, 0)
    assert interactive.shape({"n": 9, "p99": 3617, "max": 8115, "peak": 4}, 262144) == (4, 15360, 14468)
    assert interactive.shape({"n": 9, "p99": 100, "max": 200, "peak": 1}, 262144) == (1, context.FLOOR, context.FLOOR)
    assert interactive.shape({"n": 9, "p99": 7926, "max": 33968, "peak": 2}, 32768) == (2, 32768, 33968)
    assert interactive.shape({"n": 9, "p99": 30000, "max": 9, "peak": 3}, 262144)[1] == interactive.POOL_CTX
    write_gguf(tmp_path / "m.gguf", LLAMA)
    per = context.kv_bytes_per_token(context.read_meta(tmp_path / "m.gguf"))
    got = interactive.size("m", tmp_path, {"n": 9, "p99": 3617, "max": 8115, "peak": 4})
    assert (got["slots"], got["ctx"], got["kv"]) == (4, 15360, per * 15360)
    assert got["bytes"] == got["weights"] + per * 15360 + interactive.COMPUTE_BYTES
    asked = []
    interactive.choose({"decide": DECIDE}, {}, REPO / "gateway" / "config.yaml",
                       sized=lambda stem, d, got=None: asked.append(got), demands={"decide": {"n": 1}})
    assert asked == [{"n": 1}]


def test_infovores_model_keeps_its_router_alias_when_extract_pins_the_same_gguf(pinned, held):
    served = {e["model_name"]: e["litellm_params"] for e in gateway.served(
        REPO / "gateway" / "config.yaml", defaults={"claims": "Qwen2.5-7B-Instruct-Q4_K_M"}, nodes=[])["model_list"]}
    assert served["sohot-extract"]["api_base"] == f"{URL}/v1"
    for name in ("eval-7b", EXTRACT, "sohot-claims"):
        assert serving.bare(served[name]["api_base"]) == router.url(), name


def test_choose_pins_each_lane_model_and_falls_back_to_the_typed_default_when_the_budget_runs_out():
    defaults = {"decide": DECIDE, "extract": "mlx-community/Qwen2.5-7B-Instruct-4bit",
                "code": "llamacpp:Ornith-1.5-35B-Q4_K_M,temperature=0.6"}
    typed = {"decide": DECIDE, "extract": "mlx-community/Qwen2.5-7B-Instruct-4bit",
             "code": "mlx-community/Qwen3-4B-Instruct-2507-4bit"}
    sizes = {DECIDE: 5.7, EXTRACT: 6.6, "Ornith-1.5-35B-Q4_K_M": 21.3, "Qwen3-4B-Instruct-2507-Q4_K_M": 7.3}
    assert interactive.BUDGET_GB == 35.0
    ornith = interactive.choose(defaults, typed, REPO / "gateway" / "config.yaml", sized=_sized(sizes))
    assert ornith["lanes"]["code"]["stem"] == "Ornith-1.5-35B-Q4_K_M" and ornith["lanes"]["code"]["why"] == "the lane's model"
    got = interactive.choose(defaults, typed, REPO / "gateway" / "config.yaml", budget_gb=25, sized=_sized(sizes))
    assert {lane: p["stem"] for lane, p in got["lanes"].items()} == {
        "decide": DECIDE, "extract": EXTRACT, "code": "Qwen3-4B-Instruct-2507-Q4_K_M"}
    assert "Ornith-1.5-35B-Q4_K_M needs 21.3 GiB with 12.7 of 25.0 GiB left" in got["lanes"]["code"]["why"]
    assert got["bytes"] == sum(int(sizes[s] * GIB) for s in (DECIDE, EXTRACT, "Qwen3-4B-Instruct-2507-Q4_K_M"))
    small = interactive.choose(defaults, typed, REPO / "gateway" / "config.yaml", budget_gb=10, sized=_sized(sizes))
    assert list(small["lanes"]) == ["decide"]
    assert "extract" in small["skipped"] and "4.3 of 10.0 GiB left" in small["skipped"]["extract"]
    assert ornith["lanes"]["code"]["served"] == "llamacpp:Ornith-1.5-35B-Q4_K_M,temperature=0.6"


def test_the_code_lane_resolves_to_ornith_on_the_interactive_server(monkeypatch):
    ornith = "Ornith-1.5-35B-Q4_K_M"
    interactive.write({"url": URL, "bytes": 33 * GIB, "lanes": {"code": _entry(ornith, 21.3)}, "skipped": {}})
    monkeypatch.setattr(router, "statuses", lambda get=None, base="": {ornith: "loaded"} if serving.bare(base) == URL
                        else {})
    spec, where = delegate.route("code")
    assert (spec, where.base, where.model) == (f"llamacpp:{ornith}", URL, ornith)


def test_the_pinned_set_is_resident_to_the_eval_planner_and_the_load_guard(pinned, monkeypatch):
    assert interactive.reserved_bytes() == 11 * GIB
    monkeypatch.setattr(memory, "available_gb", lambda: 100.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 60.0)
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 55.0)
    assert not memory.check_model("org/m", reserve_gb=0.0)[0]
    assert memory.room_gb.__name__ and memory.pinned_gb() == 11.0
    interactive.write({**pinned, "url": "http://192.0.2.10:8083"})
    assert interactive.reserved_bytes() == 0 and memory.check_model("org/m", reserve_gb=0.0)[0]


def test_the_router_plan_leaves_the_pinned_set_room(pinned, tmp_path, monkeypatch):
    rows = [{"path": str(tmp_path / "m.gguf"), "id": 1}]
    write_gguf(tmp_path / "m.gguf", LLAMA)
    monkeypatch.setattr(context, "router_rows", lambda conn: rows)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(memory, "total_gb", lambda: float(context.KV_MAX_RAM_GB))
    budget = 20 * GIB
    with_pin = context.plan(None, budget=budget, kv_cap=64 * GIB, record=False)[0]["ctx"]
    interactive.clear()
    without = context.plan(None, budget=budget, kv_cap=64 * GIB, record=False)[0]["ctx"]
    per = context.kv_bytes_per_token(context.read_meta(tmp_path / "m.gguf"))
    assert with_pin < without and with_pin * per <= budget - 11 * GIB


def test_the_server_holds_only_its_pinned_files_never_sleeps_and_may_keep_them_all(pinned, tmp_path):
    for stem in (DECIDE, EXTRACT):
        (tmp_path / f"{stem}.gguf").write_bytes(b"GGUF")
    plan = {**pinned, "lanes": {lane: {**p, "path": str(tmp_path / f"{p['stem']}.gguf")}
                                for lane, p in pinned["lanes"].items()}}
    stale = paths.home() / interactive.MODELS_NAME
    stale.mkdir(parents=True)
    (stale / "Ornith.gguf").symlink_to(tmp_path / f"{DECIDE}.gguf")
    out = tmp_path / "interactive-preset-8083.ini"
    models = interactive.preset(out, plan)
    assert sorted(p.name for p in models.iterdir()) == sorted([f"{DECIDE}.gguf", f"{EXTRACT}.gguf"])
    assert context.models_max_path(out).read_text(encoding="utf-8").strip() == "2"
    assert f"[{DECIDE}]" in out.read_text(encoding="utf-8") and "c = 32768" in out.read_text(encoding="utf-8")
    assert not out.name.startswith("llamacpp-preset-")
    script = (REPO / "scripts" / "serve-interactive.sh").read_text(encoding="utf-8")
    assert "LLAMACPP_SLEEP_IDLE=-1" in script and "exec scripts/serve-llamacpp.sh" in script
    assert 'if [ -n "${LLAMACPP_PRESET:-}" ] ||' in (REPO / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")


def test_warm_loads_every_missing_pinned_model_and_repoints_a_stale_gateway(pinned, monkeypatch, tmp_path,
                                                                             _no_real_services):
    monkeypatch.setenv(gateway.ENV_VAR, str(tmp_path / "config.yaml"))
    seen = iter([None, {DECIDE: "unloaded"}])
    posts = []
    got = interactive.warm(pinned, interactive.WARM_WAIT_S, get=lambda path: next(seen) or (_ for _ in ()).throw(OSError("down")),
                           post=lambda path, body: posts.append((path, body)), sleep=lambda s: None)
    assert got["up"] and posts == [("/models/load", {"model": s}) for s in sorted((DECIDE, EXTRACT))]
    assert _no_real_services == []
    served = gateway.served_path()
    served.write_text("model_list:\n- model_name: sohot-decide\n  litellm_params: {model: openai/x, api_base: y}\n",
                      encoding="utf-8")
    interactive.warm(pinned, interactive.WARM_WAIT_S, get=lambda path: {"data": [{"id": DECIDE, "status": {"value": "loaded"}}]},
                     post=lambda path, body: None, sleep=lambda s: None)
    assert _no_real_services == ["gateway"]


def test_the_watchdog_restarts_a_down_missing_or_drifted_interactive_server(pinned, monkeypatch):
    hands = wd.Hands.__new__(wd.Hands)
    kicks = []
    hands._kickstart = lambda service: kicks.append(service) or f"restarted {service}"
    for state in ({"up": True, "missing": [EXTRACT], "drift": {}},
                  {"up": False, "missing": [DECIDE, EXTRACT], "drift": {}},
                  {"up": True, "missing": [], "drift": {"code": ["Qwen3-4B", "Ornith"]}}):
        w = wd.World(now=0.0, interactive={"planned": True, **state})
        found, _ = wd.judge(w)
        f = next(f for f in found if f.criterion == "interactive_down")
        assert wd.BY_ID["interactive_down"].action == wd.RESTART and hands.restart(f) == "restarted interactive"
    assert kicks == ["interactive"] * 3
    calm = {"planned": True, "up": True, "missing": [], "drift": {}}
    for state in (calm, {"planned": False}, {}):
        assert interactive.finding(wd.World(now=0.0, interactive=state)) == []
    monkeypatch.setattr(interactive, "health", lambda plan=None, get=None: {"planned": True, "up": True, "missing": []})
    monkeypatch.setattr(interactive, "plan_now", lambda **kw: {"lanes": {"decide": _entry("other")}})
    assert interactive.watch(False) == {}
    assert interactive.watch(True)["drift"] == {"decide": [DECIDE, "other"], "extract": [EXTRACT, ""]}
    monkeypatch.setattr(interactive, "plan_now", lambda **kw: (_ for _ in ()).throw(OSError("store")))
    assert "drift" not in interactive.watch(True)


def test_the_probe_reports_p95_pressure_and_the_lock_for_each_lane():
    ticks = iter(range(1000))

    def call():
        return {"spec": f"llamacpp:{DECIDE}", "model": DECIDE}
    def slow_code():
        for _ in range(3):
            next(ticks)
        return call()
    got = interactive_cmd.probe(4, decide=call, complete=call, sample=lambda: type("P", (), {"level": 1})(),
                                busy=lambda: "job 0241", clock=lambda: next(ticks) * 3.0, code=slow_code)
    assert got["ok"] and got["lanes"]["decide"]["p95_s"] == 3.0 and got["lanes"]["extract"]["while_busy"] == 4
    assert got["lanes"]["code"]["calls"] == 4 and got["lanes"]["code"]["p95_s"] == 12.0
    assert interactive_cmd.p95([1.0] * 19 + [11.0]) == 1.0 and interactive_cmd.p95([1.0] * 18 + [11.0] * 2) == 11.0
    slow = interactive_cmd.probe(2, decide=call, complete=call, sample=lambda: None, busy=lambda: "",
                                 clock=lambda: next(ticks) * 11.0, code=call)
    assert not slow["ok"]


def test_the_probe_holds_the_lanes_and_target_the_delegation_report_holds(monkeypatch):
    from harness import serve_lease
    ticks = iter(range(1000))

    def call():
        return {"spec": f"llamacpp:{DECIDE}", "model": DECIDE}
    def slow_extract():
        for _ in range(3):
            next(ticks)
        return call()
    monkeypatch.setattr(serve_lease, "P95_TARGET_S", 6.0)
    monkeypatch.setattr(serve_lease, "TARGET_LANES", ("decide",))
    got = interactive_cmd.probe(2, decide=call, complete=slow_extract, sample=lambda: None, busy=lambda: "",
                                clock=lambda: next(ticks) * 3.0, code=call)
    assert got["ok"] and got["target_p95_s"] == 6.0 and got["lanes"]["extract"]["p95_s"] == 12.0

    def again():
        return interactive_cmd.probe(2, decide=call, complete=slow_extract, sample=lambda: None, busy=lambda: "",
                                     clock=lambda: next(ticks) * 3.0, code=call)["ok"]
    monkeypatch.setattr(serve_lease, "P95_TARGET_S", 2.0)
    assert not again()
    monkeypatch.setattr(serve_lease, "P95_TARGET_S", 6.0)
    monkeypatch.setattr(serve_lease, "TARGET_LANES", ("decide", "extract"))
    assert not again()


def test_memory_warn_gives_back_eval_router_models_never_the_pinned_ones(pinned, monkeypatch):
    asked = []

    def statuses(get=None, base=""):
        asked.append(base)
        return {DECIDE: "loaded"} if serving.bare(base) == URL else {"Ornith-1.5-35B-Q4_K_M": "loaded"}
    monkeypatch.setattr(router, "statuses", statuses)
    assert [m["model"] for m in wd.Probes().served()] == ["Ornith-1.5-35B-Q4_K_M"] and asked == [""]
