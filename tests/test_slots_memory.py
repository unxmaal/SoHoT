"""Slots, pools and memory planning: what the router and the MLX server are given matches what was priced. #699."""
import configparser
import json
import subprocess
from pathlib import Path

import pytest

from harness import context, downloads, gateway, memory, serving, throughput
from harness import memory_store as ms
from tests.test_context import GIB, ORNITH, QWEN3_4B, write_gguf


@pytest.fixture(autouse=True)
def _ram_the_cap_was_set_on(monkeypatch):
    """The KV cap scales with RAM (#692); a 7 GB CI runner must price these plans as the dev box does."""
    monkeypatch.setattr(memory, "total_gb", lambda: float(context.KV_MAX_RAM_GB))


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _gguf(conn, models, stem, meta, repo="org/m"):
    p = models / f"{stem}.gguf"
    write_gguf(p, meta)
    downloads.record(conn, repo, downloads.GGUF, p, file=p.name)
    return p


def _ini(text):
    cp = configparser.ConfigParser()
    cp.read_string("[top]\n" + text)
    return cp


def _main(tmp_path, monkeypatch, budget=60 * GIB):
    monkeypatch.delenv("LLAMACPP_PARALLEL", raising=False)
    monkeypatch.delenv("LLAMACPP_MAX_MODELS", raising=False)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(context, "budget_bytes", lambda conn=None: budget)
    out = tmp_path / "preset.ini"
    assert context.main([str(out)]) == 0
    return out


def test_an_unnamed_gguf_and_the_default_section_get_more_than_one_slot_with_no_env(
        conn, models, tmp_path, monkeypatch):
    _gguf(conn, models, "Other", QWEN3_4B)
    _gguf(conn, models, context.ORNITH_STEM, ORNITH)
    cp = _ini(_main(tmp_path, monkeypatch).read_text(encoding="utf-8"))
    assert int(cp["Other"]["parallel"]) > 1
    assert int(cp["*"]["parallel"]) > 1
    assert cp[context.ORNITH_STEM]["parallel"] == str(context.ORNITH_SLOTS)


def test_choose_returns_the_pool_of_every_slot_not_one_slot():
    one = context.choose(QWEN3_4B, weights=10 * GIB, budget=16 * GIB)
    four = context.choose(QWEN3_4B, weights=10 * GIB, budget=16 * GIB, slots=4, floor=1024)
    slot = one.ctx // 4 // 1024 * 1024
    assert four.slot_ctx == slot
    assert four.ctx == 4 * slot


def test_the_preset_c_for_a_parallel_model_is_the_pool(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    _gguf(conn, models, "Other", QWEN3_4B)
    got = context.plan(conn, budget=60 * GIB, slots=4, kv_cap=8 * GIB)[0]
    assert got["slots"] == 4
    per_slot = 8 * GIB // 147456 // 4 // 1024 * 1024
    assert got["ctx"] == 4 * per_slot
    cp = _ini(context.preset_text([got], default_ctx=16384, slots=4))
    assert cp["Other"]["c"] == str(4 * per_slot)


def test_two_resident_router_models_together_fit_the_budget(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(context, "_weights", lambda path: 6 * GIB)
    _gguf(conn, models, "A", QWEN3_4B)
    _gguf(conn, models, "B", QWEN3_4B)
    budget = 30 * GIB
    got = context.plan(conn, budget=budget, kv_cap=64 * GIB, models_max=2)
    assert all(p["ctx"] for p in got)
    held = sum(6 * GIB + p["ctx"] * 147456 for p in got)
    assert held <= budget


def test_models_max_is_derived_from_the_plan_and_the_launcher_uses_it(
        conn, models, tmp_path, monkeypatch):
    monkeypatch.setattr(context, "_ram_models_max", lambda: 2)
    _gguf(conn, models, "Other", QWEN3_4B)
    out = _main(tmp_path, monkeypatch)
    assert context.models_max_path(out).read_text(encoding="utf-8").strip() == "2"
    _gguf(conn, models, "Second", QWEN3_4B)
    monkeypatch.setattr(context, "_weights", lambda path: 29 * GIB)
    out = _main(tmp_path, monkeypatch)
    assert context.models_max_path(out).read_text(encoding="utf-8").strip() == "1"


def _mlx(tmp_path, monkeypatch, weights_gib=18, layers=64, kv_heads=8, head_dim=128):
    d = tmp_path / "mlx"
    d.mkdir()
    (d / "config.json").write_text(json.dumps(
        {"num_hidden_layers": layers, "num_key_value_heads": kv_heads, "head_dim": head_dim,
         "num_attention_heads": 64, "hidden_size": 5120}), encoding="utf-8")
    (d / "model.safetensors").write_bytes(b"\0")
    real_size = memory.size_gb
    monkeypatch.setattr(memory, "size_gb", lambda path: weights_gib if Path(path) == d else real_size(path))
    monkeypatch.setattr(memory, "cache_path", lambda repo: str(d))
    monkeypatch.setattr(memory, "available_gb", lambda: 80.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 72.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 6.0)
    return d


def test_check_model_prices_the_kv_of_every_parallel_request(tmp_path, monkeypatch):
    _mlx(tmp_path, monkeypatch)
    alone, _ = memory.check_model("mlx-community/Qwen2.5-32B-4bit", reserve_gb=6.0)
    assert alone
    ok, why = memory.check_model("mlx-community/Qwen2.5-32B-4bit", reserve_gb=6.0, parallel=16)
    assert not ok, why


def test_the_gateway_caps_a_big_mlx_model_below_the_default_parallel(tmp_path, monkeypatch):
    _mlx(tmp_path, monkeypatch)
    cap = serving.mlx_parallel("mlx-community/Qwen2.5-32B-4bit")
    assert 1 <= cap < serving.MLX_MAX_PARALLEL
    entry = {"model_name": "big", "litellm_params": {
        "model": "openai/mlx-community/Qwen2.5-32B-4bit", "api_base": "http://127.0.0.1:8081/v1"}}
    got = gateway._capped(entry, {"model_list": [entry]})
    assert got["litellm_params"]["max_parallel_requests"] == cap
    ok, _ = memory.check_model("mlx-community/Qwen2.5-32B-4bit", reserve_gb=6.0, parallel=cap)
    assert ok


def _sysctl(answers):
    def run(argv, **kw):
        key = argv[-1]
        if key in answers:
            return subprocess.CompletedProcess(argv, 0, stdout=f"{answers[key]}\n", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unknown oid")
    return run


def test_the_unified_ceiling_is_the_wired_limit_when_one_is_set(monkeypatch):
    monkeypatch.setattr(memory.subprocess, "run", _sysctl({
        "hw.memsize": 96 * GIB, "iogpu.wired_limit_mb": 80 * 1024}))
    assert memory.ceiling_gb() == pytest.approx(80.0)
    assert memory.ceiling_for(memory.detect()) == pytest.approx(80.0)


def test_the_unified_ceiling_falls_back_to_the_fraction_without_a_wired_limit(monkeypatch):
    monkeypatch.setattr(memory.subprocess, "run", _sysctl({
        "hw.memsize": 96 * GIB, "iogpu.wired_limit_mb": 0}))
    assert memory.ceiling_gb() == pytest.approx(96 * memory.GPU_FRACTION)


def _smi(lines):
    def run(argv, **kw):
        if argv[0] == "nvidia-smi":
            return subprocess.CompletedProcess(argv, 0, stdout="\n".join(lines) + "\n", stderr="")
        raise OSError("not here")
    return run


def test_a_two_card_machine_budgets_both_cards(monkeypatch):
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    monkeypatch.setattr(memory.subprocess, "run", _smi(
        ["0, GPU-aaaa, RTX 4070, 12288, 10240", "1, GPU-cccc, RTX 4070, 12288, 11264"]))
    got = memory._discrete()
    assert got.total_gb == pytest.approx(24.0)
    assert got.available_gb == pytest.approx(21.0)


MIXED = ["0, GPU-aaaa-4070, RTX 4070, 12288, 10240", "1, GPU-bbbb-3090, RTX 3090, 24576, 20480"]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:CUDA_VISIBLE_DEVICES")
def test_cuda_visible_devices_chooses_the_cards(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    monkeypatch.setattr(memory.subprocess, "run", _smi(MIXED))
    got = memory._discrete()
    assert got.total_gb == pytest.approx(24.0) and "3090" in got.name


def test_a_card_named_by_uuid_is_the_card_budgeted(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-bbbb")
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)
    monkeypatch.setattr(memory.subprocess, "run", _smi(MIXED))
    got = memory._discrete()
    assert got is not None and "3090" in got.name and got.total_gb == pytest.approx(24.0)


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:CUDA_DEVICE_ORDER")
def test_a_cuda_index_in_fastest_first_order_on_mixed_cards_budgets_the_smaller(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")
    monkeypatch.delenv("CUDA_DEVICE_ORDER", raising=False)
    monkeypatch.setattr(memory.subprocess, "run", _smi(MIXED))
    got = memory._discrete()
    assert got.total_gb == pytest.approx(12.0) and "4070" in got.name


def test_the_unified_ceiling_is_metal_s_recommended_working_set_without_a_wired_limit(monkeypatch):
    monkeypatch.setattr(memory.subprocess, "run", _sysctl({
        "hw.memsize": 96 * GIB, "iogpu.wired_limit_mb": 0}))
    monkeypatch.setattr(memory, "_metal_info", lambda: {"max_recommended_working_set_size": 80 * GIB})
    assert memory.ceiling_gb() == pytest.approx(80.0)
    assert memory.ceiling_for(memory.detect()) == pytest.approx(80.0)


def test_a_screen_prices_one_request_of_kv_beside_the_weights(tmp_path, monkeypatch):
    from harness import screen
    from harness.commands import screen as screen_cmd
    _mlx(tmp_path, monkeypatch, weights_gib=60)
    row = {"name": "mlx-community/Big-4bit", "candidate": "mlx-community/Big-4bit",
           "state": screen.READY, "modality": "code"}
    assert memory.check_model(row["name"], spec=row["candidate"], reserve_gb=6.0)[0]
    assert screen_cmd.screenable_backlog(plan=[row]) == []


def test_mlx_parallel_leaves_the_router_s_planned_models_their_room(conn, models, tmp_path, monkeypatch):
    _mlx(tmp_path, monkeypatch)
    alone = serving.mlx_parallel("mlx-community/Qwen2.5-32B-4bit")
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 18 * GIB)
    monkeypatch.setattr(context, "_ram_models_max", lambda: 1)
    _gguf(conn, models, "Other", QWEN3_4B)
    planned = context.plan(conn, budget=66 * GIB, kv_cap=20 * GIB)[0]
    router = planned["ctx"] * 147456
    cap = serving.mlx_parallel("mlx-community/Qwen2.5-32B-4bit")
    assert cap < alone
    assert (18 + cap * 8) * GIB + router <= 66 * GIB


def test_the_launcher_starts_the_router_with_the_plan_s_models_max_over_the_env_cap(tmp_path):
    import os
    import shutil
    import sys
    from pathlib import Path

    import shells
    bash = shells.resolve("bash")
    if bash is None or sys.platform == "win32":
        pytest.skip("needs bash")
    repo = Path(__file__).resolve().parents[1]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "llama-server"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    uv = bindir / "uv"
    uv.write_text('#!/usr/bin/env bash\n'
                  'if [ "$4" = "harness.context" ]; then echo "[*]" > "$5"; echo 2 > "$5.models-max"; echo "$5"; exit 0; fi\n'
                  f'exec {shutil.which("uv")} "$@"\n', encoding="utf-8")
    for f in (fake, uv):
        f.chmod(0o755)
    hf = tmp_path / "hf"
    (hf / "gguf").mkdir(parents=True)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "LLAMACPP_BIN": str(fake),
           "HF_HOME": str(hf), "HF_ROOT": str(hf), "HF_MIN_FREE_GB": "0", "LLAMACPP_PORT": "0",
           "LLAMACPP_MAX_MODELS": "3"}
    out = subprocess.run([bash, str(repo / "scripts" / "serve-llamacpp.sh")],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    args = out.stdout.split("\n")
    assert args[args.index("--models-max") + 1] == "2"


def test_the_warm_up_waits_the_load_timeout_and_levels_scale_theirs(monkeypatch):
    seen = []

    def factory(base, timeout):
        def post(payload):
            seen.append(timeout)
            return {"usage": {"completion_tokens": 1}}
        return post
    monkeypatch.setattr(throughput, "_gateway_post", factory)
    throughput.sweep("m", ["a", "b"], levels=(1, 4), gateway="http://x", timeout=300.0)
    from harness import completion
    assert seen[0] >= completion.LOAD_TIMEOUT_S
    assert max(seen[1:]) >= 4 * 300.0 and min(seen[1:]) == 300.0


def test_the_default_levels_reach_past_the_measured_knees():
    import inspect
    levels = inspect.signature(throughput.sweep).parameters["levels"].default
    levels = throughput.default_levels() if levels is None else levels
    assert 8 in levels and max(levels) > max(context.EVAL_7B_SLOTS, context.ORNITH_SLOTS)


def test_the_default_reply_budget_is_the_lane_budget_not_300():
    from harness import cli, completion
    a = cli.build_parser().parse_args(["throughput", "--model", "m", "--texts", "x"])
    assert a.max_tokens in (None, completion.MAX_TOKENS)
    assert 8 in [int(x) for x in a.levels.split(",")]


def test_a_reply_cut_at_the_budget_is_flagged_and_not_counted_answered():
    def post(payload):
        return {"usage": {"completion_tokens": payload["max_tokens"]},
                "choices": [{"finish_reason": "length", "message": {"content": "x"}}]}
    got = throughput.sweep("m", ["a", "b"], levels=(1,), post=post, max_tokens=10)[0]
    assert got["truncated"] == 2
    assert got["per_hour"] == 0.0


def test_the_router_is_started_with_the_models_max_its_plan_was_sized_for(tmp_path, monkeypatch):
    from tests.test_context_store import _serve
    monkeypatch.delenv("LLAMACPP_MAX_MODELS", raising=False)
    args, _, _ = _serve(tmp_path, monkeypatch)
    preset = args[args.index("--models-preset") + 1]
    assert args[args.index("--models-max") + 1] == context.models_max_path(preset).read_text(encoding="utf-8").strip()


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:LLAMACPP_MAX_MODELS")
def test_an_explicit_models_max_is_the_one_the_plan_is_sized_for(conn, models, tmp_path, monkeypatch):
    _gguf(conn, models, "Other", QWEN3_4B)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(context, "budget_bytes", lambda conn=None: 60 * GIB)
    monkeypatch.setenv("LLAMACPP_MAX_MODELS", "3")
    out = tmp_path / "preset.ini"
    assert context.main([str(out)]) == 0
    assert context.models_max_path(out).read_text(encoding="utf-8").strip() == "3"
    text = (context.Path(context.__file__).parents[1] / "scripts" / "serve-llamacpp.sh").read_text(encoding="utf-8")
    assert 'MAX_MODELS="${LLAMACPP_MAX_MODELS:-}"' in text


def _studio(conn, models, monkeypatch):
    """Ornith beside a 4B second model on the Studio's numbers in #748: 54 GiB budget, 16 GiB MLX beside."""
    monkeypatch.delenv("LLAMACPP_MAX_MODELS", raising=False)
    monkeypatch.setattr(memory, "total_gb", lambda: 96.0)
    monkeypatch.setattr(context, "ORNITH_SLOTS", 4)
    monkeypatch.setattr(context, "ORNITH_SLOT_CTX", 262144)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 16 * GIB)
    monkeypatch.setattr(context, "budget_bytes", lambda conn=None: 54 * GIB)
    monkeypatch.setattr(context, "_ram_models_max", lambda: 2)
    monkeypatch.setattr(context, "_weights", lambda p: 20 * GIB if context.ORNITH_STEM in str(p) else 4 * GIB)
    _gguf(conn, models, context.ORNITH_STEM, ORNITH)
    _gguf(conn, models, "Second", QWEN3_4B)


def test_a_shared_pool_smaller_than_slots_times_ctx_keeps_the_slots_and_the_per_request_cap(
        conn, models, monkeypatch):
    _studio(conn, models, monkeypatch)
    alone = {p["stem"]: p for p in context.plan(conn, slots=4, record=False)}
    plans, k = context.plan_router(conn, slots=4)
    got = {p["stem"]: p for p in plans}[context.ORNITH_STEM]
    assert k == 2
    assert got["slots"] == alone[context.ORNITH_STEM]["slots"] == 3, got["why"]
    assert 262144 <= got["ctx"] < 3 * 262144, got["why"]
    share = (54 - 16 - 24) * GIB // 2
    assert got["ctx"] * context.kv_bytes_per_token(ORNITH) <= share
    cp = _ini(context.preset_text(plans, default_ctx=16384, slots=4))
    assert cp[context.ORNITH_STEM]["parallel"] == "3" and cp[context.ORNITH_STEM]["kv-unified"] == "true"

    def down(url):
        raise OSError("refused")
    assert context.served_ctx(f"llamacpp:{context.ORNITH_STEM}", get=down) == 262144


def test_router_bytes_counts_the_residents_the_recorded_plan_was_sized_for(conn, models, monkeypatch):
    from harness import paths
    monkeypatch.setattr(context, "_ram_models_max", lambda: 2)
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0)
    monkeypatch.setattr(context, "budget_bytes", lambda conn=None: 60 * GIB)
    monkeypatch.setattr(context, "_weights", lambda path: 29 * GIB)
    _gguf(conn, models, "A", QWEN3_4B)
    _gguf(conn, models, "B", QWEN3_4B)
    out = paths.home() / "llamacpp-preset-8082.ini"
    assert context.main([str(out)]) == 0
    assert context.models_max_path(out).read_text(encoding="utf-8").strip() == "1"
    held = [29 * GIB + int(r["ctx"]) * 147456 for r in downloads.live(conn, kind=downloads.GGUF)]
    assert context.router_bytes(conn) == max(held)


def test_a_full_shared_pool_is_a_limit_not_the_model_s_failure():
    from harness import paired, reasons
    # The body llama-server 0.5.0 b11146 answered every in-flight request with when its unified pool filled. #748.
    text = ('gateway returned HTTP 500: {"error":{"code":500,"message":"Context size has been exceeded.",'
            '"type":"server_error"}}')
    got = reasons.classify(text, reasons.RUNNER, "llamacpp:Ornith-1.5-35B-Q4_K_M")
    assert got == reasons.POOL_FULL
    assert reasons.CLASSES[got][1] == reasons.LIMIT
    assert got in paired.UNJUDGED
