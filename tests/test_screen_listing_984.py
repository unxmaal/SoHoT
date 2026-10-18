"""The listing and tag rules #949 added to screen, tested where the nightly mutates screen. #984."""
import pytest

from harness import screen, variants

FLOOR = screen.ADAPTER_FLOOR_BYTES


def f(name, size=0):
    return {"rfilename": name, "size": size}


def v(fmt, *files):
    return variants.Variant(fmt, tuple(files), 1)


@pytest.mark.parametrize("files,config,found,want", [
    (None, None, None, None),
    ([], None, [], screen.EMPTY),
    ([f("README.md")], None, [], screen.EMPTY),
    ([f("adapter_config.json")], None, None, screen.ADAPTER),
    (["Adapter_Config.json"], None, None, screen.ADAPTER),
    ([f("ADAPTER_MODEL.safetensors", 10)], None, None, screen.ADAPTER),
    ([{"size": 3}, f("adapter_model.bin", 10)], None, None, screen.ADAPTER),
    ([f("a/b/adapter_config.json"), f("a/b/w.safetensors", 10)], None, [], screen.ADAPTER),
    ([f("a/b/adapter_model.safetensors", 10)], None, [], screen.ADAPTER),
    ([f("x_adapter_config.json"), f("w.safetensors", 10)], None, [], screen.LOOSE),
    ([f("model_index.json")], None, [], screen.MODEL),
    ([f("model_index.json"), f("sub/adapter_config.json")], None, [], screen.MODEL),
    ([f("sub/model_index.json")], None, [], screen.EMPTY),
    ([f("w.safetensors", 10)], {"model_type": "llama"}, [], screen.MODEL),
    ([f("w.safetensors", 10)], {"architectures": ["LlamaForCausalLM"]}, [], screen.MODEL),
    ([f("w.safetensors", 10)], {}, [], screen.LOOSE),
    ([f("w.safetensors", FLOOR - 1)], None, [], screen.LOOSE),
    ([f("w.safetensors", FLOOR)], None, [], screen.BULK),
    ([f("config.json"), f("w.safetensors", FLOOR)], None, [], screen.LOOSE),
    ([f("sub/config.json"), f("w.safetensors", FLOOR)], None, [], screen.BULK),
    ([f("w.safetensors", FLOOR)], None, [v(variants.DIFFUSERS, "unet/w.safetensors")], screen.MODEL),
    ([f("w.safetensors", FLOOR)], None, [v(variants.MISTRAL, "consolidated.safetensors")], screen.MODEL),
    ([f("w.safetensors", FLOOR)], None, [v(variants.GGUF, "m-Q4_K_M.gguf")], screen.MODEL),
    ([f("w.safetensors", FLOOR)], None, [v(variants.COMFYUI, "unet/m.safetensors")], screen.MODEL),
    ([f("w.safetensors", FLOOR)], None, [v(variants.GGUF, "m-LoRA-F16.gguf")], screen.BULK),
    ([f("w.safetensors", FLOOR)], None, [v(variants.COMFYUI, "loras/m_Adapter.safetensors")], screen.BULK),
    ([f("w.safetensors", FLOOR)], None, [v(variants.GGUF, "m-Q4.gguf", "m-lora.gguf")], screen.BULK),
    ([f("w.safetensors", FLOOR)], None, [v(variants.CHECKPOINT, "w.safetensors")], screen.BULK),
    ([f("m-Q4_K_M.gguf", FLOOR)], None, None, screen.MODEL),
])
def test_a_listing_says_what_it_is(files, config, found, want):
    assert screen.listing_kind(files, config, found) == want


def test_a_listing_is_read_through_its_own_variants_when_none_are_given():
    assert screen.listing_kind([f("checkpoints/m.safetensors", FLOOR)]) == screen.MODEL


@pytest.mark.parametrize("words,files,config,found,want", [
    (["lora"], [f("model_index.json")], None, [], ""),
    (["lora"], [f("w.safetensors", 10)], {"model_type": "llama"}, [], ""),
    (["lora"], [f("w.safetensors", 10)], None, [v(variants.DIFFUSERS, "unet/w.safetensors")], ""),
    (["lora"], [f("w.safetensors", 10)], None, [], "lora"),
    (["mixture-of-lora"], None, None, None, ""),
    ("mixture-of-lora", None, None, None, "lora"),
    (["mixture-of-lora"], [f("w.safetensors", 10)], None, [], screen.ADAPTER),
    (["mixture-of-lora"], [f("w.safetensors", FLOOR)], None, [], ""),
    ([], [f("adapter_config.json")], None, None, screen.ADAPTER),
    (["plugin"], [f("w.safetensors", FLOOR)], None, [], ""),
    (["plugin"], [f("README.md")], None, [], "plugin"),
    (["plugin"], None, None, None, "plugin"),
])
def test_the_listing_decides_an_attachment(words, files, config, found, want):
    assert screen.is_attachment(words, files, config, found) == want


@pytest.mark.parametrize("words,want", [
    (["Xtts"], ["xtts"]),
    (["(LoRA),"], ["lora"]),
    (["dataset:foo", "license:mit", "lora"], ["lora"]),
    (["dataset"], ["dataset"]),
    (["hf:lora"], ["lora"]),
    (["hf:lora:extra"], ["lora:extra"]),
    (["dataset:a:b"], []),
    (["lora:"], ["lora:"]),
    (["lora-ready", ""], []),
    ("gui lora", ["gui", "lora"]),
    (None, []),
])
def test_tags_are_whole_lowered_and_foreign_namespaces_dropped(words, want):
    assert screen._tags(words) == want


@pytest.mark.parametrize("tags,want", [
    (["lora"], ("lora", True)),
    (["mixture-of-lora"], ("lora", False)),
    (["llama"], ("", False)),
])
def test_a_weight_word_says_whether_a_whole_tag_names_it(tags, want):
    assert screen._weight_word(tags) == want


@pytest.mark.parametrize("word,tags,want", [
    ("adapter", [], True),
    (" LoRA ", ["LoRA"], True),
    ("lora", ["hf:lora"], True),
    ("lora", ["gui"], False),
    ("gui", ["gui"], False),
    ("plugin", ["plugin"], True),
    (None, ["lora"], False),
    ("", [""], False),
])
def test_tags_support_only_a_word_the_current_rule_would_store(word, tags, want):
    assert screen.tags_support(word, tags) is want


GAP = "needs its own runner: its card names the comfyui library, weights packaged for ComfyUI, which no engine here loads"


@pytest.mark.parametrize("card,want", [
    ({"library": "comfyui"}, GAP),
    ({"library_name": " ComfyUI "}, GAP),
    ({"library": "", "library_name": "comfyui"}, GAP),
    ({"library": "comfyui", "library_name": "transformers"}, GAP),
    ({"library": "transformers"}, ""),
    (None, ""),
])
def test_a_card_naming_a_foreign_library_is_a_runner_gap(card, want):
    assert screen.runner_gap("text", "org/m", card=card) == want


def test_a_runtime_gap_reads_its_why_and_evidence_as_one_text():
    got = screen.decide_class("load_failed_runtime", why="Model type llama", evidence="not supported",
                              candidate="org/m")
    assert got.until == "runner:transformers"


def test_a_receipt_for_another_candidate_is_a_harness_error():
    got = screen.outcome(0, {"other/x": {"passed": 1}}, candidate="org/m")
    assert (got.outcome, got.reason, got.failure_class) == ("queued", "harness", "harness_error")


def test_a_degenerate_screen_joins_its_caveat_to_the_sampler_check():
    row = {"passed": 0, "failure_classes": {"degenerate": 2}, "screen_caveat": "two cases",
           "screen_until": "limit:screen_cases>6"}
    got = screen.outcome(0, {"org/m": row}, candidate="org/m")
    assert got.detail.endswith(f"two cases; {screen.SAMPLER_CHECK}")


def test_the_card_chooses_a_runtime_gaps_until_with_or_without_a_receipt():
    card = {"library": "paddle"}
    row = {"passed": 0, "failure_classes": {"load_failed_runtime": 1}}
    assert screen.outcome(0, {"org/m": row}, candidate="org/m", card=card).until == "runner:paddle"
    assert screen.outcome(1, None, candidate="org/m", stderr_class="load_failed_runtime",
                          card=card).until == "runner:paddle"


def test_a_screen_with_no_candidate_reads_every_row():
    assert screen.outcome(0, {"a": {"passed": 2}}).outcome == "screened"
