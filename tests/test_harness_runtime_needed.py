"""Can THIS machine run these weights? Issue #245.

`rank.unrunnable` knew exactly one format. Four candidates in the live queue
were tagged `cuda`, `gemlite`, `nvfp4` and `modelopt`, ranked, and would have
been fetched and handed to a runner that cannot load them -- with the screen
then recording a verdict about the CANDIDATE. That is the eighth instance of
a harness-side gap settling a real model.

The answer is a RUNTIME NAME, never a verdict, because it is a fact about the
machine asking. The same gemlite weights are perfectly runnable on a box with
a card, and the store is shared between machines.

Since #414 it is read from the card's fields by inspect and stored as
proposals.runtime_needed; rank reads the column.
"""
import pytest

from harness import inspect as ins
from harness import machine as _machine
from harness import rank
from harness.memory import Accelerator

#: Real cards, as the store recorded them, in the registry's field shape.
GEMLITE = {"pipeline_tag": "text-to-image", "library_name": "diffusers",
           "tags": ["1-bit", "gemlite", "hqq", "cuda", "text-to-image",
                    "diffusion",
                    "base_model:quantized:prism-ml/bonsai-image-binary-4B-unpack"]}
NVFP4 = {"pipeline_tag": "text-generation", "library_name": "transformers",
         "tags": ["gemma4", "text-generation", "nvfp4", "modelopt", "vllm",
                  "base_model:quantized:google/gemma-4-31B-it"]}
VLLM = {"pipeline_tag": "automatic-speech-recognition", "library_name": "vllm",
        "tags": ["vllm", "voxtral_realtime", "mistral-common", "fr", "es"]}
MLX = {"pipeline_tag": "automatic-speech-recognition", "library_name": "mlx",
       "tags": ["mlx", "mistral-common", "automatic-speech-recognition", "fr",
                "es", "de"]}
TRANSFORMERS = {"pipeline_tag": "text-generation",
                "library_name": "transformers",
                "tags": ["qwen2", "text-generation", "math", "code", "reasoning",
                         "base_model:finetune:Qwen/Qwen2.5-Coder-3B"]}


def mac():
    return _machine.Machine(frozenset({"mlx", "cpu"}),
                            Accelerator("unified", 32.0, 25.0, "Mac14,12"))


def card():
    return _machine.Machine(frozenset({"cuda", "vllm", "cpu"}),
                            Accelerator("discrete", 12.0, 11.0, "RTX 4070"))


def row(data, name="org/m", lane="image"):
    """A queue row carrying what inspect stored from this card."""
    return {"name": name, "lane": lane,
            "description": ins.card_description(data),
            "runtime_needed": ins.card_facts(data).runtime_needed}


@pytest.mark.parametrize("data,want", [
    (GEMLITE, "cuda"), (NVFP4, "cuda"), (VLLM, "vllm"),
])
def test_a_card_that_names_its_runtime_is_read(data, want):
    assert ins.card_facts(data).runtime_needed == want


@pytest.mark.parametrize("data", [MLX, TRANSFORMERS, {},
                                  {"tags": ["qwen3", "moe"]}])
def test_a_card_that_does_not_name_a_foreign_runtime_is_left_alone(data):
    """THE NEGATIVE CONTROL, and the half that decides whether this ships.

    A filter that fires on everything empties the queue and reads exactly like
    a queue that ran out. `transformers` is deliberately not refused: torch
    runs here, and what a conversion costs is a different question.
    """
    assert ins.card_facts(data).runtime_needed == ""


def test_the_answer_is_a_fact_about_the_machine_asking():
    """The store is shared. The same weights are unrunnable here and ordinary
    on the box with the card, so this must never be written down as a verdict
    about the candidate."""
    assert rank.unrunnable(row(GEMLITE), mac()) == "needs-cuda"
    assert rank.unrunnable(row(GEMLITE), card()) == ""


def test_unrunnable_reads_the_column_not_the_description():
    """#414. The description still says `cuda` for the judge; a reader that
    parses it again fails here, where the column is empty."""
    r = {**row(GEMLITE), "runtime_needed": ""}
    assert rank.unrunnable(r, mac()) == ""


def test_vllm_is_probed_rather_than_assumed_absent():
    """Without a probe, refuses("vllm") answers needs-vllm on the box that HAS
    one, which is the mirror of the mistake #228 made about GGUF."""
    assert "vllm" in _machine._RUNTIME_PROBES
    assert rank.unrunnable(row(VLLM, lane="stt"), card()) == ""


def test_awq_and_gptq_are_deliberately_not_refused():
    """They are quantisation formats with CUDA kernels in practice and
    implementations elsewhere. Refusing them would be PREDICTING a failure
    rather than reading one, which is how a filter starts settling candidates
    on our guesses."""
    for fmt in ("awq", "gptq"):
        assert ins.runtime_needed("", ["qwen3", fmt, "text-generation"]) == ""


def test_an_mlx_card_survives_on_the_mac():
    assert rank.unrunnable(row(MLX, name="mlx-community/x", lane="stt"),
                           mac()) == ""
