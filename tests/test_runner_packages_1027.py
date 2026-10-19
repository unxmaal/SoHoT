"""#1027: each runner package a screen can wait on is pinned in the venv whose runner imports it, or is not a runner package."""
import re
import sys
from pathlib import Path

import pytest

from harness import reasons, runner_gaps

ROOT = Path(__file__).resolve().parent.parent

#: dist -> the venv whose runner's model families import it.
PINNED = {"scipy": "diffusers-cuda", "torchsde": "diffusers-cuda", "timm": "hf-task", "tiktoken": "hf-task",
          "protobuf": "hf-task", "ftfy": "diffusers-cuda", "beautifulsoup4": "diffusers-cuda"}
#: module -> why no runner here can raise it.
DROPPED = {"einops": "no runner library imports it; only remote code, which hf-task refuses",
           "onnx": "no runner library imports it; mlx-audio only in its convert scripts",
           "imwatermark": "diffusers SDXL turns its watermark off when the package is absent",
           "note_seq": "only diffusers' deprecated MIDI SpectrogramDiffusion pipeline, which no lane feeds",
           "librosa": "only diffusers and transformers audio pipelines, which neither runner venv serves",
           "cv2": "ConsisID, legacy export_to_video and PP-OCR detection/layout, none of which a runner here loads",
           "peft": "only nimble imports it, and nimble-venv.sh pins it"}


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
@pytest.mark.parametrize("dist,venv", sorted(PINNED.items()))
def test_a_runner_package_is_pinned_in_the_venv_its_runner_imports_from(monkeypatch, platform, dist, venv):
    monkeypatch.setattr(sys, "platform", platform)
    assert runner_gaps.provides(dist, venv), f"{dist} has no pin in {venv}'s venv script"


@pytest.mark.parametrize("dist", sorted(PINNED))
def test_each_pin_names_one_exact_version(dist):
    pins = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert re.search(rf'^[A-Z0-9_]+_PIN="{re.escape(dist)}==\d+(\.\d+)+"$', pins, re.M), dist


@pytest.mark.parametrize("module", sorted(DROPPED))
def test_a_module_no_runner_can_raise_is_not_a_runner_package(module):
    assert module not in reasons.RUNNER_PACKAGES
    assert reasons.missing_package(f"exit 1: ModuleNotFoundError: No module named '{module}'") == ""
    assert reasons.classify(f"exit 1: No module named '{module}'", reasons.RUNNER, "diffusers:a/b") \
        == reasons.HARNESS_ERROR

