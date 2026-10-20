"""#1031: diffusers' and transformers' "requires the <lib> library" texts name a package the runner venv lacks."""
import pytest

from harness import reasons, screen

LMS = ("LMSDiscreteScheduler requires the scipy library but it was not found in your environment. "
       "You can install it with pip: `pip install scipy`")
SDE = ("DPMSolverSDEScheduler requires the torchsde library but it was not found in your environment. "
       "You can install it with pip: `pip install torchsde`")
BETA = "Make sure to install scipy if you want to use beta sigmas."
TORCHVISION = ("AutoImageProcessor requires the Torchvision library but it was not found in your environment. "
               "Check out the instructions on the installation page")


@pytest.mark.parametrize("spec,venv", [("diffusers:org/m", "diffusers-cuda"), ("hf-ocr:org/m", "hf-task")])
@pytest.mark.parametrize("text,dist", [(LMS, "scipy"), (SDE, "torchsde"), (BETA, "scipy")])
def test_the_issue_texts_wait_on_the_package_not_the_model(text, dist, spec, venv):
    detail = f"fox-snow: exit 1: {text}"
    assert reasons.missing_package(detail) == dist
    assert reasons.classify(detail, reasons.RUNNER, spec) == reasons.MISSING_PACKAGE
    v = screen.decide_class(reasons.MISSING_PACKAGE, detail, spec)
    assert (v.outcome, v.reason, v.until) == ("declined", reasons.RUNTIME, f"package:{dist}@{venv}")


@pytest.mark.parametrize("text,dist", [
    (TORCHVISION, "torchvision"),
    ("XLMRobertaConverter requires the protobuf library but it was not found in your environment.", "protobuf"),
    ("MarkupLMFeatureExtractor requires the Beautiful Soup library but it was not found in your environment.",
     "beautifulsoup4"),
    ("T5Tokenizer requires the SentencePiece library but it was not found in your environment.", "sentencepiece"),
    ("Make sure to install `torchvision` to be able to use the `resolve_interpolation_mode`", "torchvision"),
    ("Make sure to install accelerate or set `low_cpu_mem_usage=False`.", "accelerate"),
    ("Make sure to install scipy.", "scipy"),
])
def test_a_library_word_maps_by_module_or_by_distribution(text, dist):
    assert reasons.missing_package(text) == dist


def test_hf_task_s_last_line_waits_on_the_package_rather_than_retrying():
    last = f"exit 4: hf-task venv lacks a package: {TORCHVISION}"
    assert reasons.classify(last, reasons.RUNNER, "hf-ocr:org/m") == reasons.MISSING_PACKAGE
    v = screen.decide_class(reasons.MISSING_PACKAGE, last, "hf-ocr:org/m")
    assert v.until == "package:torchvision@hf-task"


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/reasons.py:RUNNER_PACKAGES")
@pytest.mark.parametrize("text,cls", [
    ("FluxPipeline requires the PyTorch library but it was not found in your environment.", reasons.CRASHED),
    ("Make sure to install matplotlib if you want to use a color map other than `viridis`.", reasons.CRASHED),
    ("AutoImageProcessor requires the Torchvision library. Please note that you may need to restart your "
     "runtime after installation.", reasons.HARNESS_ERROR),
])
def test_a_library_no_runner_package_names_keeps_its_class(text, cls):
    assert reasons.missing_package(text) == ""
    assert reasons.classify(text, reasons.RUNNER, "diffusers:org/m") == cls


@pytest.mark.parametrize("module,dist", [("bs4.element", "beautifulsoup4"), ("timm.models.layers", "timm")])
def test_a_missing_submodule_waits_on_its_top_level_package(module, dist):
    assert reasons.missing_package(f"ModuleNotFoundError: No module named '{module}'") == dist


def test_an_unmapped_name_does_not_hide_a_mapped_one_after_it():
    text = "No module named 'einops'\nMarkupLMFeatureExtractor requires the Beautiful Soup library but it was not found"
    assert reasons.missing_package(text) == "beautifulsoup4"


@pytest.mark.parametrize("spelling", ["ruamel_yaml", "ruamel-yaml", "ruamel.yaml", "ruamel__yaml"])
def test_a_distribution_matches_in_any_pep503_spelling(monkeypatch, spelling):
    monkeypatch.setitem(reasons.RUNNER_PACKAGES, "ruamel_yaml_shim", "ruamel.yaml")
    assert reasons.missing_package(f"Make sure to install `{spelling}` to load this model") == "ruamel.yaml"
