"""inspect sizes a listing by its smallest runnable variant and reads its runtime from the variants, not the repo. #947."""
import time
import types

import pytest

import fakes
from harness import fetching, gguf, live_audit, rank, screen, variants
from harness import inspect as ins
from harness import memory_store as ms
from harness.commands import discover as discover_cmd

GIB = 1024 ** 3
CEILING = 66 * GIB


def _machine(*runtimes):
    have = set(runtimes) | {"always"}
    return types.SimpleNamespace(runtimes=frozenset(have),
                                 refuses=lambda rt: None if rt in have else f"needs-{rt}")


MAC = _machine("mlx", "llamacpp")


def _file(card, name) -> int:
    return next(s["size"] for s in card["siblings"] if s["rfilename"] == name)


def _total(card) -> int:
    return sum(s.get("size") or 0 for s in card["siblings"])


def _fit(repo, card=None, ceiling=CEILING, machine=MAC):
    return ins.inspect_model(repo, data=card or fakes.card(repo), ceiling=ceiling, machine=machine)


@pytest.mark.parametrize("repo, expect", [
    ("OBLITERATUS/Qwen3.8-27B-OBLITERATED", lambda c: _file(c, "Qwen3.8-27B-OBLITERATED-Q4_K_M.gguf")),
    ("Comfy-Org/MiniMax-H3", lambda c: _file(c, "diffusion_models/minimax_h3_fl2va_pruned_w6a8.safetensors")
        + _file(c, "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors")
        + _file(c, "vae/minimax_h3_audio_vae_fp32.safetensors")),
    ("lodestones/Kroma", lambda c: _file(c, "kroma-sensei-booru-e6-teacher-velocity-v0.3.safetensors")),
    ("mistralai/Shieldstral-1.0-3B", lambda c: _file(c, "model.safetensors")),
    # mlx-audio opens every *.safetensors offline, so both copies are what it runs from. #1040.
    ("mistralai/Voxtral-Mini-4B-Realtime-2602", lambda c: _file(c, "consolidated.safetensors")
        + _file(c, "model.safetensors")),
    ("mistralai/Mistral-7B-Instruct-v0.3", lambda c: sum(
        _file(c, f"model-0000{i}-of-00003.safetensors") for i in (1, 2, 3))),
])
def test_a_recorded_listing_is_sized_by_one_variant_and_is_not_refused(repo, expect):
    card = fakes.card(repo)
    fit = _fit(repo, card)
    assert fit.verdict == "fits", fit.why
    assert fit.largest == fit.smallest == expect(card) < _total(card)
    assert fit.why.startswith(variants.MARK) or fit.why.startswith("MLX-native, " + variants.MARK)
    assert fit.variant.split(":")[0].split(" (+")[0] in {s["rfilename"] for s in card["siblings"]}


def test_a_comfy_tree_passes_over_a_cuda_only_encoder_while_another_is_listed():
    fit = _fit("Comfy-Org/MiniMax-H3")
    assert "nvfp4" not in fit.variant
    assert fit.variant.startswith("diffusion_models/") and "(+2)" in fit.variant


def test_a_single_variant_transformers_listing_is_still_too_big_and_names_its_variant():
    repo = "CohereLabs/command-a-plus-05-2026-bf16"
    card = fakes.card(repo)
    fit = _fit(repo, card)
    assert fit.verdict == "too-big"
    assert fit.smallest == _total(card) - sum(s["size"] for s in card["siblings"]
                                              if not s["rfilename"].endswith(".safetensors"))
    assert fit.why.startswith(variants.MARK + "model-00001-of-00009.safetensors (+8): 407.5 GiB")
    assert ins.until_of(fit) == "ceiling_gb:>407.5"


def test_a_vllm_tag_beside_a_loadable_copy_is_a_fact_on_the_card_not_a_refusal():
    for repo in ("mistralai/Shieldstral-1.0-3B", "mistralai/Voxtral-Mini-4B-Realtime-2602",
                 "mistralai/Mistral-7B-Instruct-v0.3"):
        card = ins.card_facts(fakes.card(repo))
        assert card.library == "vllm"
        assert card.runtime_needed == "", repo
        assert rank.unrunnable({"name": repo, "runtime_needed": card.runtime_needed}, MAC) == ""
    for repo in ("mistralai/Shieldstral-1.0-3B", "mistralai/Mistral-7B-Instruct-v0.3"):
        assert screen.candidate_for("code", repo) == repo


def test_a_consolidated_only_listing_still_needs_vllm():
    card = fakes.card("mistralai/Mistral-7B-Instruct-v0.3")
    card["siblings"] = [s for s in card["siblings"] if not s["rfilename"].startswith("model")
                        and s["rfilename"] != "config.json"]
    assert {s["rfilename"] for s in card["siblings"]} >= {"consolidated.safetensors", "params.json"}
    facts = ins.card_facts(card)
    assert facts.runtime_needed == "vllm"
    assert rank.unrunnable({"name": "x", "runtime_needed": facts.runtime_needed}, MAC) == "needs-vllm"


def test_without_a_listing_the_library_tag_still_answers():
    assert ins.runtime_needed("vllm", ()) == "vllm"
    assert ins.runtime_needed("vllm", (), found=[]) == "vllm"
    assert ins.runtime_needed("transformers", ("nvfp4",), found=[]) == "cuda"


def test_the_stt_reader_takes_voxtral_from_its_consolidated_file_not_the_hf_copy():
    card = fakes.card("mistralai/Voxtral-Mini-4B-Realtime-2602")
    found = variants.variants(card["siblings"], CEILING, model_type="voxtral_realtime")
    assert [v.files for v in found] == [("consolidated.safetensors",)]
    other = variants.variants(card["siblings"], CEILING, model_type="mistral")
    assert {v.format for v in other} == {variants.HF, variants.MISTRAL}


def _unknown_layout() -> dict:
    files = [("weights/part-a.safetensors", 40.0), ("weights/part-b.safetensors", 40.0),
             ("README.md", 0.0001)]
    return {"id": "org/odd-layout", "pipeline_tag": "text-to-image", "tags": [],
            "siblings": [{"rfilename": n, "size": int(g * GIB)} for n, g in files]}


def test_weights_no_variant_groups_are_queued_as_our_gap_never_too_big_on_the_sum():
    fit = _fit("org/odd-layout", _unknown_layout())
    assert fit.verdict == "unknown"
    assert ins.reason_of(fit) == "harness"
    assert ins.until_of(fit) == "layout:weights/*.safetensors"
    small = _unknown_layout()
    for s in small["siblings"]:
        s["size"] //= 8
    assert _fit("org/odd-layout", small).verdict == "fits"


def test_the_inspect_writer_queues_an_ungrouped_layout_with_reason_harness(monkeypatch):
    card = _unknown_layout()
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=card["id"], source="t", resolved=card["id"], kind="weights",
                                registry=ms.HUGGINGFACE, lane="image"))
    finally:
        conn.close()
    monkeypatch.setattr(discover_cmd, "resolve_registry",
                        lambda name, client, model=None: (ms.HUGGINGFACE, card))
    real = ins.inspect_model
    monkeypatch.setattr(ins, "inspect_model",
                        lambda repo, data=None, **kw: real(repo, data=data, ceiling=CEILING, machine=MAC))
    from harness import cli
    assert cli.main(["discover", "--inspect", "--repos", card["id"]]) == 0
    conn = ms.connect()
    try:
        row = conn.execute("SELECT v.outcome, v.reason, v.until FROM proposals p "
                           "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?",
                           (card["id"],)).fetchone()
    finally:
        conn.close()
    assert tuple(row) == ("queued", "harness", "layout:weights/*.safetensors")


def _pin_fetch(monkeypatch):
    from harness import machine
    monkeypatch.setattr(machine, "detect", lambda *a, **k: MAC)
    monkeypatch.setattr(ins, "ceiling_bytes", lambda acc=None: CEILING)


def test_fetch_downloads_only_the_variant_inspect_sized(monkeypatch, tmp_path):
    _pin_fetch(monkeypatch)
    card = fakes.card("mistralai/Mistral-7B-Instruct-v0.3")
    asked = {}

    def snapshot(repo_id, **kw):
        asked.update(kw, repo_id=repo_id)
        return str(tmp_path)

    fetching.download(card["id"], snapshot=snapshot, listing=lambda r: card["siblings"],
                      text=True, require_weights=True)
    allow = asked["allow_patterns"]
    assert "consolidated.safetensors" not in allow
    assert {"model-00001-of-00003.safetensors", "config.json", "params.json"} <= set(allow)


def test_fetch_takes_one_gguf_from_a_listing_whose_smallest_variant_is_a_quant(monkeypatch):
    _pin_fetch(monkeypatch)
    card = fakes.card("OBLITERATUS/Qwen3.8-27B-OBLITERATED")
    got = []
    monkeypatch.setattr(gguf, "download", lambda repo, name, **kw: got.append(name) or name)
    fetching.download(card["id"], snapshot=lambda **kw: pytest.fail(f"snapshot {kw}"),
                      listing=lambda r: card["siblings"], text=True, require_weights=True)
    assert got == ["Qwen3.8-27B-OBLITERATED-Q4_K_M.gguf"]


def test_a_single_variant_listing_downloads_as_before(monkeypatch, tmp_path):
    _pin_fetch(monkeypatch)
    card = fakes.card("CohereLabs/command-a-plus-05-2026-bf16")
    asked = []
    fetching.download(card["id"], snapshot=lambda repo_id, **kw: asked.append(kw) or str(tmp_path),
                      listing=lambda r: card["siblings"], text=False, require_weights=True)
    assert asked == [{}]


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _see(conn, name, registry=ms.HUGGINGFACE):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights",
                            registry=registry, lane="code"))


def _too_big(conn, name, detail, registry=ms.HUGGINGFACE):
    _see(conn, name, registry)
    ms.decide(conn, name, "declined", tier=ms.INSPECT, reason="machine", until="ceiling_gb:>223.2",
              detail=detail, ceiling_gb=66.0)


def _needs_vllm(conn, name, inspected):
    _see(conn, name)
    ms.decide(conn, name, "queued", tier=ms.INSPECT, reason="candidate", detail=inspected)
    ms.decide(conn, name, "declined", tier="fetch", reason="machine", until="runtime:vllm",
              detail="needs-vllm: this machine has no runtime that can load these weights")


OLD = "too-big: smallest weight it names is 223.2 GiB, over the 66 GiB ceiling"
NEW = "too-big: smallest variant m-00001-of-00009.safetensors (+8): 407.5 GiB of 9 weight files, over the 66 GiB ceiling"


@pytest.mark.gauntlet("state-is-whichever-row-came-last",
                      site="harness/memory_store/revisit.py:runtime_by_library")
def test_refusals_sized_the_old_way_are_reinspected_once(store):
    _too_big(store, "org/summed", OLD)
    _too_big(store, "org/variant", NEW)
    _too_big(store, "org/ds4", "too-big: x.gguf: 70.0 GiB resident, over the 66 GiB ceiling")
    _too_big(store, "org/source", OLD, registry=ms.GITHUB)
    _needs_vllm(store, "org/tagged", "fits: weights from 27.0 to 27.0 GiB")
    _needs_vllm(store, "org/read", "fits: smallest variant consolidated.safetensors: 13.5 GiB of 1 weight file")
    assert sorted(ms.requeue_old_sizing(store)) == ["org/summed", "org/tagged"]
    states = dict(store.execute("SELECT name, state FROM proposals").fetchall())
    assert states["org/summed"] == states["org/tagged"] == "queued"
    assert "org/summed" in ms.pending(store, screened=False)
    assert ms.requeue_old_sizing(store) == []
    ms.decide(store, "org/tagged", "queued", tier=ms.INSPECT, reason="candidate",
              detail="fits: smallest variant consolidated.safetensors: 13.5 GiB of 1 weight file")
    ms.decide(store, "org/tagged", "declined", tier="fetch", reason="machine", until="runtime:vllm",
              detail="needs-vllm: this machine has no runtime that can load these weights")
    assert ms.requeue_old_sizing(store) == []


def test_the_audit_counts_too_big_verdicts_that_name_no_variant(store):
    assert live_audit._too_big_names_variant(store, None) == ([], [])
    _too_big(store, "org/summed", OLD)
    _too_big(store, "org/variant", NEW)
    failed, warned = live_audit._too_big_names_variant(store, None)
    assert failed == [] and len(warned) == 1 and "1 too-big" in warned[0] and "org/summed" in warned[0]
    failed, _ = live_audit._too_big_names_variant(store, time.time() + 1)
    assert len(failed) == 1 and "org/summed" in failed[0]
    assert "too_big_names_variant" in live_audit.CHECKS


def test_the_loop_runs_the_sizing_requeue_with_the_ceiling_one(monkeypatch):
    from harness.commands import loop as loop_cmd
    conn = ms.connect()
    try:
        _too_big(conn, "org/summed", OLD)
    finally:
        conn.close()
    assert "org/summed" in loop_cmd._reopen_stale_too_big()


def test_a_listing_with_no_weight_files_keeps_its_old_sum():
    card = {"id": "org/nemo", "pipeline_tag": "automatic-speech-recognition", "tags": [],
            "siblings": [{"rfilename": "m.tflite", "size": 2 * GIB}, {"rfilename": "README.md", "size": 10}]}
    fit = _fit("org/nemo", card)
    assert fit.largest == 2 * GIB + 10 and not fit.variant and not fit.layout

