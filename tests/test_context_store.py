"""The served context is a row beside the GGUF source, and the router preset reads it. #498."""
import configparser
import sqlite3

import pytest

from harness import context, downloads
from harness import memory_store as ms
from tests.test_context import GIB, ORNITH, QWEN3_4B, write_gguf


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


def test_the_store_carries_the_served_context_beside_the_gguf_row(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(downloads)")}
    assert {"ctx", "ctx_trained", "kv_bytes_token", "ctx_slots", "ctx_why",
            "ctx_at"} <= cols


def test_plan_records_each_gguf_row_and_its_reason(conn, models):
    _gguf(conn, models, "Ornith", ORNITH, repo="org/ornith")
    _gguf(conn, models, "Tiny", {**QWEN3_4B, "qwen3.context_length": 4096})
    got = {p["stem"]: p for p in context.plan(conn, budget=60 * GIB)}
    assert got["Ornith"]["ctx"] == 262144
    assert got["Tiny"]["ctx"] == 0 and "refused" in got["Tiny"]["why"]
    row = context.served(conn, "Ornith")
    assert row["ctx"] == 262144 and row["ctx_trained"] == 262144
    assert row["kv_bytes_token"] == 20480 and row["ctx_slots"] == 1
    assert "trained" in row["ctx_why"] and row["ctx_at"]
    assert context.served(conn, "Tiny")["ctx"] == 0


def test_a_dense_model_beside_a_resident_mlx_model_keeps_its_kv_under_the_cap(
        conn, models, monkeypatch):
    monkeypatch.delenv("LLAMACPP_KV_MAX_GIB", raising=False)
    _gguf(conn, models, "Dense", QWEN3_4B)
    monkeypatch.setattr(context, "_weights", lambda path: int(2.3 * GIB))
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 17 * GIB,
                        raising=False)
    budget = 54 * GIB
    got = context.plan(conn, budget=budget)[0]
    kv = got["ctx"] * 147456
    assert 8192 <= got["ctx"] and kv <= 8 * GIB
    assert int(2.3 * GIB) + kv + 17 * GIB <= budget
    row = context.served(conn, "Dense")
    assert row["kv_cap_bytes"] == 8 * GIB and row["coresident_bytes"] == 17 * GIB


def test_a_hybrid_keeps_its_trained_context_under_the_cap(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 17 * GIB,
                        raising=False)
    _gguf(conn, models, "Ornith", ORNITH)
    assert context.plan(conn, budget=54 * GIB)[0]["ctx"] == 262144


def test_the_kv_cap_is_configurable(conn, models, monkeypatch):
    monkeypatch.setenv("LLAMACPP_KV_MAX_GIB", "2")
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0, raising=False)
    _gguf(conn, models, "Dense", QWEN3_4B)
    got = context.plan(conn, budget=54 * GIB)[0]
    assert got["ctx"] == 2 * GIB // 147456 // 1024 * 1024


def test_the_coresident_model_is_the_largest_adopted_mlx_text_model(conn, tmp_path):
    cfg = tmp_path / "gw.yaml"
    cfg.write_text("model_list:\n"
                   "  - model_name: q3-30b\n    litellm_params:\n"
                   "      model: openai/mlx-community/Qwen3-30B-4bit\n"
                   "      api_base: http://127.0.0.1:8081/v1\n"
                   "  - model_name: q3-4b\n    litellm_params:\n"
                   "      model: openai/mlx-community/Qwen3-4B-4bit\n"
                   "      api_base: http://127.0.0.1:8081/v1\n", encoding="utf-8")
    sizes = {"mlx-community/Qwen3-30B-4bit": 17 * GIB,
             "mlx-community/Qwen3-4B-4bit": 2 * GIB}
    got = context.coresident_bytes(
        conn, defaults={"svg": "q3-30b", "code": "llamacpp:Ornith", "web": "q3-4b",
                        "image": "mflux:z-image-turbo"},
        config=cfg, size_of=sizes.get)
    assert got == 17 * GIB


def test_the_weights_come_off_the_budget(conn, models, monkeypatch):
    p = _gguf(conn, models, "Q", QWEN3_4B)
    monkeypatch.setattr(context, "_weights", lambda path: 10 * GIB)
    got = context.plan(conn, budget=16 * GIB)[0]
    assert got["ctx"] == (6 * GIB) // 147456 // 1024 * 1024
    assert str(p) == got["path"]


def test_an_unreadable_header_is_refused_not_raised(conn, models):
    p = models / "Broken.gguf"
    p.write_bytes(b"junk")
    downloads.record(conn, "org/b", downloads.GGUF, p, file=p.name)
    got = context.plan(conn, budget=60 * GIB)[0]
    assert got["ctx"] == 0 and "unreadable" in got["why"]


def test_a_removed_or_missing_file_is_not_planned(conn, models):
    p = _gguf(conn, models, "Gone", ORNITH)
    p.unlink()
    assert context.plan(conn, budget=60 * GIB) == []


def test_the_default_budget_is_the_ceiling_less_the_measured_reserve(conn, monkeypatch):
    from harness import memory
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 72.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 6.0)
    assert context.budget_bytes(conn) == 66 * GIB


def _ini(text: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser()
    cp.read_string("[top]\n" + text)
    return cp


def test_the_preset_gives_each_servable_model_its_own_context():
    plans = [{"stem": "Ornith", "ctx": 262144, "why": "trained"},
             {"stem": "Q", "ctx": 40960, "why": "memory"}]
    cp = _ini(context.preset_text(plans, default_ctx=16384, slots=1))
    assert cp["*"]["c"] == "16384" and cp["*"]["parallel"] == "1"
    assert cp["Ornith"]["c"] == "262144" and cp["Q"]["c"] == "40960"


def test_more_slots_share_one_pool_so_one_request_can_use_it_all():
    cp = _ini(context.preset_text([{"stem": "A", "ctx": 65536, "why": ""}],
                                  default_ctx=16384, slots=4))
    assert cp["A"]["parallel"] == "4" and cp["A"]["kv-unified"] == "true"
    assert cp["A"]["c"] == "65536"


def test_a_refused_model_gets_no_section_and_its_reason_is_written():
    text = context.preset_text([{"stem": "Tiny", "ctx": 0,
                                 "why": "refused: trained for 4096"}],
                               default_ctx=16384, slots=1)
    assert "Tiny" not in _ini(text).sections()
    assert "; Tiny refused: trained for 4096" in text


def test_route_refuses_a_stem_whose_recorded_context_is_under_the_floor(conn, models):
    from harness import serving
    _gguf(conn, models, "Tiny", {**QWEN3_4B, "qwen3.context_length": 4096})
    context.plan(conn, budget=60 * GIB)
    conn.commit()
    with pytest.raises(ValueError, match="refused: trained for 4096"):
        serving.route("llamacpp:Tiny")


def test_route_serves_a_stem_with_no_recorded_context():
    from harness import serving
    assert serving.route("llamacpp:Unrecorded").model == "Unrecorded"


def _serve(tmp_path, monkeypatch, *, broken=False):
    """Run serve-llamacpp.sh against a fake llama-server that prints its argv."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    import shells
    bash = shells.resolve("bash")
    if bash is None or sys.platform == "win32":
        pytest.skip("needs bash")
    repo = Path(__file__).resolve().parents[1]
    fake = tmp_path / "llama-server"
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    home = Path(os.environ["LOCALHARNESS_HOME"])
    hf = tmp_path / "hf"
    (hf / "gguf").mkdir(parents=True)
    env = {**os.environ, "LLAMACPP_BIN": str(fake), "HF_HOME": str(hf),
           "HF_ROOT": str(hf), "HF_MIN_FREE_GB": "0", "LLAMACPP_PORT": "0",
           "LOCALHARNESS_HOME": str(home)}
    if broken:
        env["LLAMACPP_PARALLEL"] = "not-a-number"
    out = subprocess.run([bash, str(repo / "scripts" / "serve-llamacpp.sh")],
                         capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.split("\n"), out.stderr, home


def test_the_router_reads_its_contexts_from_the_preset_not_one_ctx_size(
        tmp_path, monkeypatch):
    args, _, home = _serve(tmp_path, monkeypatch)
    preset = args[args.index("--models-preset") + 1]
    assert "--ctx-size" not in args
    assert preset.startswith(str(home)) and "[*]" in open(preset).read()


def test_the_router_still_gets_a_context_when_the_preset_cannot_be_written(
        tmp_path, monkeypatch):
    args, err, _ = _serve(tmp_path, monkeypatch, broken=True)
    assert "--models-preset" not in args
    assert args[args.index("--ctx-size") + 1] == "16384"
    assert "per-model context" in err


def test_an_older_store_gains_the_columns(tmp_path):
    path = tmp_path / "old.db"
    ms.connect(path).close()
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE d2 AS SELECT id, proposal_id, repo, kind, path, file, "
                "origin, source, bytes, files, complete, requires, started_at, "
                "finished_at, removed_at, removed_by, removal_verdict_id, "
                "machine_id FROM downloads")
    raw.execute("DROP TABLE downloads")
    raw.execute("ALTER TABLE d2 RENAME TO downloads")
    raw.execute("UPDATE meta SET value = ? WHERE key = 'schema'",
                ("44",))
    raw.commit()
    raw.close()
    c = ms.connect(path)
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(downloads)")}
        assert "ctx" in cols and "ctx_why" in cols
    finally:
        c.close()


def test_eval_7b_gets_its_slots_and_a_pool_of_slots_times_the_slot_context(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0, raising=False)
    monkeypatch.setattr(context, "EVAL_7B_SLOTS", 8)
    monkeypatch.setattr(context, "EVAL_7B_SLOT_CTX", 4096)
    _gguf(conn, models, context.EVAL_7B_STEM, QWEN3_4B)
    _gguf(conn, models, "Other", QWEN3_4B)
    got = {p["stem"]: p for p in context.plan(conn, budget=60 * GIB)}
    seven = got[context.EVAL_7B_STEM]
    assert seven["slots"] == 8 and seven["ctx"] == 8 * 4096
    assert got["Other"]["slots"] == 1
    row = context.served(conn, context.EVAL_7B_STEM)
    assert row["ctx_slots"] == 8 and row["ctx"] == 32768
    cp = _ini(context.preset_text(list(got.values()), default_ctx=16384, slots=1))
    assert cp[context.EVAL_7B_STEM]["parallel"] == "8" and cp[context.EVAL_7B_STEM]["c"] == "32768"
    assert cp[context.EVAL_7B_STEM]["kv-unified"] == "true"
    assert cp["Other"]["parallel"] == "1"


def test_a_slot_context_under_the_floor_is_refused_not_served(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0, raising=False)
    monkeypatch.setattr(context, "EVAL_7B_SLOTS", 8)
    monkeypatch.setattr(context, "EVAL_7B_SLOT_CTX", context.MIN_SLOT_CTX - 1024)
    _gguf(conn, models, context.EVAL_7B_STEM, QWEN3_4B)
    with pytest.raises(ValueError, match="3072"):
        context.plan(conn, budget=60 * GIB)


def test_a_slot_pool_that_does_not_fit_the_kv_cap_is_refused(conn, models, monkeypatch):
    monkeypatch.setattr(context, "coresident_bytes", lambda conn: 0, raising=False)
    monkeypatch.setattr(context, "EVAL_7B_SLOTS", 32)
    monkeypatch.setattr(context, "EVAL_7B_SLOT_CTX", 16384)
    _gguf(conn, models, context.EVAL_7B_STEM, QWEN3_4B)
    got = context.plan(conn, budget=60 * GIB, kv_cap=8 * GIB)[0]
    assert got["ctx"] == 0 and "refused" in got["why"] and "32 slots" in got["why"]
