"""#950, #951: a runner that cannot load a repo waits on what its cause lacks, and a runner layout gap is never broken."""
import json
import subprocess

import pytest

from harness import engines, live_audit, machine, reasons, runner_gaps, screen
from harness import memory_store as ms
from harness.memory_store import revisit
from harness.memory_store.migrations import retractions

INSTALLED = {"versions": {"mlx-lm": "0.32.0", "diffusers": "0.40.0", "transformers": "5.16.1",
                          "hf-task/transformers": "5.17.0", "ace-step": "1.5.0"}}


@pytest.fixture(autouse=True)
def _installed(monkeypatch):
    real = ms.this_machine()
    monkeypatch.setattr(ms, "this_machine", lambda: {**real, **INSTALLED})


def _gateway(error: str) -> str:
    return f'chunk-bytes: warm-up: gateway returned HTTP 404: {{"error": "{error}"}}'


def _vlm(mtype: str, tags=()) -> dict:
    return {"hf_task": "image-text-to-text", "library": "transformers",
            "card_tags": json.dumps([mtype, "image-text-to-text", *tags])}


def _text(mtype: str, tags=()) -> dict:
    return {"hf_task": "text-generation", "library": "transformers",
            "card_tags": json.dumps([mtype, "text-generation", *tags])}


REMOTE_OCR = ("ocr-invoice-line: exit 3: needs its own runner: baidu/Unlimited-OCR ships its own "
              "modelling code (trust_remote_code), which hf-task never executes")

# (verdict, candidate, card, failure text, class, the until the cause names), from the live store 2026-10-17.
AUDITED = [
    (11180, "LiquidAI/LFM2.5-VL-3B", _vlm("lfm2_vl", ["custom_code"]),
     _gateway("Model type lfm2_vl not supported."), reasons.LOAD_FAILED_RUNTIME, "runner:mlx-vlm"),
    (8778, "openbmb/MiniCPM-V-4.6", _vlm("minicpmv4_6"),
     _gateway("Model type minicpmv4_6 not supported."), reasons.LOAD_FAILED_RUNTIME, "runner:mlx-vlm"),
    (6543, "CohereLabs/North-Micro-Vision-Instruct", _vlm("cohere_compass"),
     _gateway("Model type cohere_compass not supported."), reasons.LOAD_FAILED_RUNTIME, "runner:mlx-vlm"),
    (6546, "sapientinc/HRM-Text-1B", _text("hrm_text"),
     _gateway("Model type hrm_text not supported."), reasons.LOAD_FAILED_RUNTIME, "runner:transformers"),
    (6549, "TokenRhythm/NeoHorse-1-4B", _text("qwen3_5_text"),
     _gateway("Model type qwen3_5_text not supported."), reasons.LOAD_FAILED_RUNTIME, "runner:transformers"),
    (6545, "FrontiersMind/Nandi-Mini-600M-Early-Checkpoint", _text("nandi", ["custom_code"]),
     _gateway("Model type nandi not supported."), reasons.LOAD_FAILED_RUNTIME,
     "policy:trust_remote_code@nandi"),
    (8323, "EschaLabs/Qwen3.6-35B-A3B-Escha-W2",
     {"hf_task": "text-generation", "library": "mlx", "card_tags": '["mlx", "qwen3_5_moe", "2-bit"]'},
     _gateway("Received 984 parameters not in model: \\nlanguage_model.lm_head.weight_int8,\\n"
              "language_model.lm_head.weight_scale,\\nlanguage_model.model.embed_tokens.weight_int8"),
     reasons.LOAD_FAILED_RUNTIME, "format:weight_int8"),
    (10899, "hf-ocr:baidu/Unlimited-OCR",
     {"hf_task": "image-text-to-text", "library": "transformers", "card_tags": '["ocr", "custom_code"]'},
     REMOTE_OCR, reasons.LOAD_FAILED_LAYOUT, "policy:trust_remote_code"),
    (10898, "hf-ocr:JustANormalTinkerer/hayai-ocr-v2",
     {"hf_task": "image-to-text", "library": "transformers", "card_tags": '["ocr", "custom_code"]'},
     REMOTE_OCR.replace("baidu/Unlimited-OCR", "JustANormalTinkerer/hayai-ocr-v2"),
     reasons.LOAD_FAILED_LAYOUT, "policy:trust_remote_code"),
    (6547, "z-lab/gemma-4-31B-it-DFlash", _text("qwen3", ["dflash", "draft-model"]),
     _gateway("Received 58 parameters not in model: \\nfc.weight,\\nhidden_norm.weight,\\n"
              "layers.0.input_layernorm.weight"), reasons.LOAD_FAILED_RUNTIME, "format:unread-tensors"),
]


@pytest.mark.parametrize("vid,candidate,card,text,cls,want", AUDITED, ids=[str(a[0]) for a in AUDITED])
def test_an_audited_runtime_decline_waits_on_its_cause_not_a_release(vid, candidate, card, text, cls, want):
    v = screen.decide_class(cls, text, candidate, card=card)
    assert (v.outcome, v.reason, v.failure_class) == ("declined", reasons.RUNTIME, cls)
    assert v.until == want
    assert not v.until.startswith("version:")


def test_the_same_failure_from_stderr_alone_reaches_the_same_until():
    v = screen.outcome(1, None, candidate="LiquidAI/LFM2.5-VL-3B", stderr_class=reasons.LOAD_FAILED_RUNTIME,
                       evidence=_gateway("Model type lfm2_vl not supported."), card=_vlm("lfm2_vl"))
    assert v.until == "runner:mlx-vlm"


def test_a_text_architecture_mlx_lm_could_add_still_waits_on_its_release():
    """RULE #331: a text model type no runtime here ships is the one case a release can change."""
    v = screen.decide_class(reasons.LOAD_FAILED_RUNTIME, _gateway("Model type gpt_x not supported."),
                            "org/gpt-x", card=_text("gpt_x"))
    assert v.until == "version:mlx-lm>0.32.0"
    v = screen.decide_class(reasons.LOAD_FAILED_RUNTIME, "TypeError: __init__() missing 1 required "
                            "positional argument: 'rope_theta'", "org/m", card=_text("llama"))
    assert v.until == "version:mlx-lm>0.32.0"


def test_a_backend_fault_keeps_its_release_until():
    v = screen.decide_class(reasons.BACKEND_FAULT, "LLVM ERROR: Failed to infer result type(s): \"mps.matmul\"",
                            "diffusers:org/x", card={"library": "diffusers"})
    assert v.until == "version:diffusers>0.40.0"


def test_an_hf_task_until_names_the_hf_task_venv_version():
    v = screen.decide_class(reasons.LOAD_FAILED_RUNTIME, "ValueError: model type foo_bar not supported",
                            "hf-ocr:org/x", card={"hf_task": "image-to-text"})
    assert v.until == "version:hf-task/transformers>5.17.0"


def test_versions_record_the_hf_task_venv_under_its_own_name(tmp_path, monkeypatch):
    from harness import serving, stages
    site = tmp_path / "hf-task" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    for d in ("transformers-5.17.0.dist-info", "sentence_transformers-6.1.0.dist-info", "numpy-2.0.0.dist-info"):
        (site / d).mkdir()
    monkeypatch.setattr(stages, "tool_versions", lambda: {})
    monkeypatch.setattr(machine, "_imported_versions", lambda: {"transformers": "5.16.1"})
    monkeypatch.setattr(machine, "_other_venvs", lambda: [])
    monkeypatch.setattr(machine, "_vllm_venvs", lambda: [])
    monkeypatch.setattr(machine, "_keyed_venvs", lambda: {"hf-task": tmp_path / "hf-task"})
    monkeypatch.setattr(machine, "_uv_with_pins", lambda: {})
    monkeypatch.setattr(machine, "_mflux_cli", lambda: "")
    monkeypatch.setattr(serving, "llamacpp_build", lambda: "")
    got = machine.versions.__wrapped__()
    assert got["transformers"] == "5.16.1", "the checkout's own copy stays under its bare name"
    assert got["hf-task/transformers"] == "5.17.0"
    assert got["hf-task/sentence-transformers"] == "6.1.0"
    assert "hf-task/numpy" not in got


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:HF_TASK_VENV")
def test_the_versions_probe_reads_the_venv_the_hf_task_script_builds(tmp_path, monkeypatch):
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "scripts" / "hf-task-venv.sh").read_text(encoding="utf-8")
    assert 'HF_TASK_VENV="${HF_TASK_VENV:-${LOCALHARNESS_HOME:-$HOME/localharness}/venvs/hf-task}"' in text
    monkeypatch.delenv("HF_TASK_VENV", raising=False)
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    assert machine._keyed_venvs()["hf-task"] == tmp_path / "venvs" / "hf-task"
    monkeypatch.setenv("HF_TASK_VENV", str(tmp_path / "elsewhere"))
    assert machine._keyed_venvs()["hf-task"] == tmp_path / "elsewhere"


def test_a_weightless_engine_spelled_bare_is_not_the_text_server():
    assert runner_gaps.head_of("bm25") == "bm25" and runner_gaps.head_of("Qwen/Qwen3-4B") == ""
    assert engines.card_gap("bm25", {"library": "PaddleOCR"}) == ""


def test_the_until_keys_have_readers_that_open_only_when_the_lack_is_filled():
    assert not ms.until_met("runner:mlx-vlm", {"engines": frozenset({"mflux"})})
    assert ms.until_met("runner:mlx-vlm", {"engines": frozenset({"mflux", "mlx-vlm"})})
    assert not ms.until_met("runner:mlx-vlm")
    assert not ms.until_met("policy:trust_remote_code@nandi", {"native_types": frozenset({"llama"})})
    assert ms.until_met("policy:trust_remote_code@nandi", {"native_types": frozenset({"nandi"})})
    assert not ms.until_met("policy:trust_remote_code", {"native_types": frozenset({"nandi"})})
    assert ms.until_met("version:hf-task/transformers>5.17.0",
                        {"versions": {"hf-task/transformers": "5.18.0"}})


# ---- #951: the classifier ---------------------------------------------------

LAYOUT_DETAILS = [
    ("diffusers:Danrisi/UltraReal_FineTune_Anima_base1_v3",
     "fox-snow: exit 1: OSError: Danrisi/UltraReal_FineTune_Anima_base1_v3 does not appear to have a file "
     "named model_index.json."),
    ("diffusers:ivanmikhnenkov/tinydit-256",
     "fox-snow: exit 1: OSError: ivanmikhnenkov/tinydit-256 does not appear to have a file named model_index.json."),
    ("diffusers:SupraLabs/Supra-A2A-Nano-Exp",
     "fox-snow: exit 1: OSError: SupraLabs/Supra-A2A-Nano-Exp does not appear to have a file named "
     "model_index.json."),
    ("diffusers:kpsss34/Walkyrie-1.3B-v1.0",
     "fox-snow: exit 1: AttributeError: module diffusers has no attribute WalkyriePipeline. "
     "Did you mean: 'WanVACEPipeline'?"),
    ("QLNI/SHADOW-250M", _gateway("No safetensors found in /Volumes/MODELS/hf/hub/models--QLNI--SHADOW-250M/"
                                  "snapshots/21d2ac8aa61fe7e134aac31cdf358d1d18a84dd0")),
    ("tts:m-a-p/YuE2-3B", "long-clause: tts failed: HTTP 500: {\"detail\":\"Failed to load model "
                          "'m-a-p/YuE2-3B': Could not determine model type for m-a-p/YuE2-3B\"}"),
    ("acestep:m-a-p/YuE2-3B", "cover: exit 3"),
]


@pytest.mark.parametrize("candidate,text", LAYOUT_DETAILS, ids=[c for c, _ in LAYOUT_DETAILS])
def test_a_runner_that_cannot_open_the_layout_is_a_layout_gap(candidate, text):
    assert reasons.classify(text, reasons.RUNNER, candidate) == reasons.LOAD_FAILED_LAYOUT
    v = screen.decide_class(reasons.LOAD_FAILED_LAYOUT, text, candidate)
    assert v.outcome == "declined" and v.until and not v.until.startswith("version:")


def test_a_file_missing_from_our_own_snapshot_stays_a_harness_error():
    text = ("No such file or directory: '/Volumes/MODELS/hf/hub/models--org--x/snapshots/"
            "0123abcd/model_index.json'")
    assert reasons.classify(text, reasons.RUNNER, "diffusers:org/x") == reasons.HARNESS_ERROR


def test_a_file_the_repo_lacks_elsewhere_is_still_the_snapshots():
    text = "OSError: org/x does not appear to have a file named tokenizer.json."
    assert reasons.classify(text, reasons.RUNNER, "org/x") == reasons.MISSING_FILE_IN_SNAPSHOT


def test_an_exit_3_from_another_engine_is_not_acesteps_init_failure():
    assert reasons.classify("cover: exit 3", reasons.RUNNER, "diffusers:org/x") == reasons.CRASHED


def test_a_real_content_failure_stays_content_failed():
    summary = {"org/x": {"passed": 0, "failures": ["chunk-bytes: expected 42, got 41"],
                         "failure_classes": {reasons.CONTENT_FAILED: 1}}}
    v = screen.outcome(0, summary, candidate="org/x", key="org/x")
    assert v.failure_class == reasons.CONTENT_FAILED
    assert reasons.classify("chunk-bytes: expected 42, got 41", reasons.RUNNER, "org/x") == reasons.CRASHED


# ---- the pre-screen card gate -----------------------------------------------

CARD_GAPS = [
    ("LiquidAI/LFM2.5-VL-3B", {"hf_task": "image-text-to-text", "model_type": "lfm2_vl"}),
    ("org/remote", {"hf_task": "text-generation", "model_type": "nandi", "remote_code": "modeling_nandi.py"}),
    ("QLNI/SHADOW-250M", {"hf_task": "text-generation", "library": "shadow"}),
    ("org/vendor", {"hf_task": "text-generation", "library": "mlx", "card_tags": '["eschamoe"]'}),
    ("org/declined", {"hf_task": "text-generation", "model_type": "qwen3_5_text"}),
    ("diffusers:Danrisi/UltraReal", {"hf_task": "text-to-image", "library": "diffusers",
                                     "siblings": [{"rfilename": "UltraReal.safetensors"}]}),
    ("diffusers:ivanmikhnenkov/tinydit-256", {"hf_task": "text-to-image", "library": "pytorch"}),
    ("diffusers:SupraLabs/Supra-A2A-Nano-Exp", {"hf_task": "any-to-any",
                                                "card_tags": '["vqvae", "text-to-image"]'}),
    ("diffusers:kpsss34/Walkyrie-1.3B-v1.0", {"hf_task": "text-to-image", "library": "diffusers",
                                              "card_tags": '["diffusers", "diffusers:WalkyriePipeline"]'}),
    ("acestep:m-a-p/YuE2-3B", {"hf_task": "text-to-audio", "model_type": "yue2",
                               "remote_code": "modeling_yue2.py"}),
]


@pytest.mark.parametrize("spec,card", CARD_GAPS, ids=[s for s, _ in CARD_GAPS])
def test_a_card_the_runner_cannot_load_is_refused_before_download(spec, card):
    assert engines.card_gap(spec, card).startswith("needs its own runner: ")


CARD_FITS = [
    ("Qwen/Qwen3-4B", {"hf_task": "text-generation", "library": "transformers", "model_type": "qwen3"}),
    # #379 routes a Qwen3.5 VLM to code on purpose: mlx-lm builds its text part.
    ("apus-ailab/APUS-OpenJev-v1-4B", {"hf_task": "image-text-to-text", "model_type": "qwen3_5"}),
    ("org/unread", {"hf_task": "image-text-to-text"}),
    ("unsloth/Qwen3.5-9B-GGUF", {"hf_task": "text-generation", "library": "gguf"}),
    ("diffusers:black-forest-labs/FLUX.1-schnell",
     {"hf_task": "text-to-image", "library": "diffusers", "card_tags": '["diffusers:FluxPipeline"]',
      "siblings": [{"rfilename": "model_index.json"}, {"rfilename": "transformer/x.safetensors"}]}),
]


@pytest.mark.parametrize("spec,card", CARD_FITS, ids=[s for s, _ in CARD_FITS])
def test_a_card_the_runner_loads_passes_the_gate(spec, card):
    assert engines.card_gap(spec, card) == ""


def test_the_snapshots_are_of_the_pinned_runtimes():
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    locked = re.search(r'name = "mlx-lm"\nversion = "([^"]+)"', lock).group(1)
    assert runner_gaps.mlx_lm_types()[0] == f"mlx-lm=={locked}"
    pin = re.search(r'^DIFFUSERS_PIN="([^"]+)"', (root / "scripts" / "versions.sh").read_text(
        encoding="utf-8"), re.M).group(1)
    assert runner_gaps.diffusers_pipelines()[0] == pin
    assert "qwen3_5" in runner_gaps.mlx_lm_types()[1] and "lfm2_vl" not in runner_gaps.mlx_lm_types()[1]
    assert "FluxPipeline" in runner_gaps.diffusers_pipelines()[1]


# ---- the store: backfill, audit, failure_class --------------------------------

def _store(tmp_path):
    return ms.connect(tmp_path / "d.db")


def _seed(conn, name, lane, card, outcome, tier, detail, until="", reason="", spec=""):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane=lane, why="seeded"))
    conn.execute("UPDATE proposals SET hf_task = ?, library = ?, card_tags = ?, model_type = ?, "
                 "remote_code = ? WHERE name = ?",
                 (card.get("hf_task", ""), card.get("library", ""), card.get("card_tags", "[]"),
                  card.get("model_type", ""), card.get("remote_code", ""), name))
    from harness import candidates
    cid = candidates.ensure(conn, spec or name, proposal=name, lane=lane)
    ms.decide(conn, name, outcome, tier=tier, detail=detail, until=until, reason=reason, candidate_id=cid)


def _state(conn, name):
    return dict(conn.execute("SELECT p.state, v.until, v.failure_class FROM proposals p JOIN verdicts v "
                             "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def test_the_backfill_rewrites_live_untils_and_takes_layout_gaps_out_of_broken(tmp_path):
    conn = _store(tmp_path)
    try:
        _seed(conn, "LiquidAI/LFM2.5-VL-3B", "code", _vlm("lfm2_vl"), "declined", ms.SCREEN,
              "the installed runtime could not load it: " + _gateway("Model type lfm2_vl not supported."),
              until="version:mlx-lm>0.32.0", reason=reasons.RUNTIME)
        _seed(conn, "org/gpt-x", "code", _text("gpt_x"), "declined", ms.SCREEN,
              "the installed runtime could not load it: " + _gateway("Model type gpt_x not supported."),
              until="version:mlx-lm>0.32.0", reason=reasons.RUNTIME)
        _seed(conn, "kpsss34/Walkyrie-1.3B-v1.0", "image",
              {"hf_task": "text-to-image", "library": "diffusers"}, "broken", ms.SCREEN,
              "it ran and passed nothing: " + LAYOUT_DETAILS[3][1], reason=reasons.CANDIDATE,
              spec="diffusers:kpsss34/Walkyrie-1.3B-v1.0")
        _seed(conn, "org/really-broken", "code", _text("llama"), "broken", ms.SCREEN,
              "it ran and passed nothing: chunk-bytes: Traceback: KeyError: 'x'", reason=reasons.CANDIDATE)
        assert live_audit._runner_gap_until_current(conn, None)[1]
        assert live_audit._broken_runner_layout(conn)
        retractions._decline_runner_layout_gaps(conn)
        retractions._rewrite_runner_gap_untils(conn)
        conn.commit()
        assert _state(conn, "LiquidAI/LFM2.5-VL-3B") == {
            "state": "declined", "until": "runner:mlx-vlm", "failure_class": reasons.LOAD_FAILED_RUNTIME}
        assert _state(conn, "org/gpt-x")["until"] == "version:mlx-lm>0.32.0"
        assert _state(conn, "kpsss34/Walkyrie-1.3B-v1.0") == {
            "state": "declined", "until": "runner:diffusers/WalkyriePipeline",
            "failure_class": reasons.LOAD_FAILED_LAYOUT}
        assert _state(conn, "org/really-broken")["state"] == "broken"
        assert live_audit._runner_gap_until_current(conn, None) == ([], [])
        assert live_audit._broken_runner_layout(conn) == []
        waits = {r["name"] for r in ms.runner_waits(conn)}
        assert waits == {"LiquidAI/LFM2.5-VL-3B"}, "a migration retraction is reason reopened, not runtime"
        assert ms.rewrite_runner_gap_untils(conn) == [], "a second pass changes nothing"
    finally:
        conn.close()


def test_a_retest_that_would_rerun_a_runner_gap_waits_on_it_instead(tmp_path):
    conn = _store(tmp_path)
    try:
        card = {"hf_task": "text-to-audio", "model_type": "yue2", "remote_code": "modeling_yue2.py"}
        _seed(conn, "m-a-p/YuE2-3B", "music", card, "broken", ms.SCREEN,
              "it ran and passed nothing: cover: exit 3", reason=reasons.CANDIDATE,
              spec="acestep:m-a-p/YuE2-3B")
        ms.decide(conn, "m-a-p/YuE2-3B", "queued", tier=ms.INSPECT, detail="retest 1/3: broken at screen",
                  reopen="retest", reopen_why="retest 1/3")
        ms.decide(conn, "m-a-p/YuE2-3B", "queued", tier=ms.INSPECT, detail="fits: weights from 6.8 to 6.8 GiB")
        retractions._decline_runner_layout_gaps(conn)
        conn.commit()
        assert _state(conn, "m-a-p/YuE2-3B") == {"state": "declined", "until": "policy:trust_remote_code@yue2",
                                                  "failure_class": reasons.LOAD_FAILED_LAYOUT}
        assert conn.execute("SELECT next_retest_at FROM proposals WHERE name = 'm-a-p/YuE2-3B'").fetchone()[0] \
            is None
    finally:
        conn.close()


def test_a_card_read_before_model_type_is_reread_once(tmp_path):
    conn = _store(tmp_path)
    try:
        _seed(conn, "org/custom", "code", _text(""), "declined", ms.SCREEN,
              "the installed runtime could not load it: " + _gateway("Model type custom not supported."),
              until="version:mlx-lm>0.32.0", reason=reasons.RUNTIME)
        assert ms.cards_to_reread(conn) == ["org/custom"]
        ms.record(conn, ms.Seen(name="org/custom", source="inspect", kind="weights", lane="code", why="re-read"))
        assert ms.cards_to_reread(conn) == []
    finally:
        conn.close()


def test_a_screen_verdict_records_its_failure_class(tmp_path, monkeypatch):
    import argparse
    from harness import cli, memory
    from harness.commands import measure as measure_cmd
    from harness.commands import screen as screen_cmd
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    _seed(conn, "org/x", "image", {"hf_task": "text-to-image", "library": "diffusers"}, "queued",
          ms.INSPECT, "fits: weights from 1 to 1 GiB")
    conn.close()
    plan = [{"name": "org/x", "state": screen.READY, "candidate": "diffusers:org/x", "modality": "image",
             "why_not": "", "hf_task": "text-to-image", "library": "diffusers"}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, store: "")
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda outdir: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0] if a else [], 1, "", "OSError: org/x does not appear to have a file named model_index.json."))
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=1, run=True, json=False))
    conn = ms.connect()
    try:
        assert _state(conn, "org/x") == {"state": "declined", "until": "runner:diffusers/single-file",
                                         "failure_class": reasons.LOAD_FAILED_LAYOUT}
    finally:
        conn.close()
