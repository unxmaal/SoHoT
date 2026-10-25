"""A diffusers pipeline loads at the dtype its repo names, and a blank canvas is a numeric fault, not the model. #1013."""
import dataclasses
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from evals.core import load_cases, summarize
from harness import engines, image_diffusers, reasons, screen
from harness import torch_device as td
from harness.checks import image as image_check

ROOT = Path(__file__).resolve().parents[1]
SPEC = "diffusers:Photoroom/prxpixel-t2i"
FOX = next(c for c in load_cases(ROOT / "evals" / "cases" / "image") if c.id == "fox-snow")


def _safetensors(path: Path, dtype: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = json.dumps({"__metadata__": {"format": "pt"},
                         "w": {"dtype": dtype, "shape": [1], "data_offsets": [0, 4]}}).encode()
    path.write_bytes(struct.pack("<Q", len(header)) + header + b"\0" * 4)


def _config(path: Path, **kw) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"_class_name": "X", **kw}), encoding="utf-8")


def _prx(root: Path) -> Path:
    """Photoroom/prxpixel-t2i as the Studio holds it: transformer F32, text encoder BF16 naming bfloat16."""
    _config(root / "transformer" / "config.json")
    _safetensors(root / "transformer" / "diffusion_pytorch_model.safetensors", "F32")
    _config(root / "text_encoder" / "config.json", dtype="bfloat16")
    _safetensors(root / "text_encoder" / "model.safetensors", "BF16")
    return root


def _sdxl_turbo(root: Path) -> Path:
    """stabilityai/sdxl-turbo as fetched: every weight F32, the CLIP configs naming float16."""
    _safetensors(root / "unet" / "diffusion_pytorch_model.safetensors", "F32")
    _config(root / "text_encoder" / "config.json", torch_dtype="float16")
    _safetensors(root / "text_encoder" / "model.safetensors", "F32")
    return root


# --- 1. the dtype comes from the repo -----------------------------------------

def test_prx_declares_bfloat16_through_its_text_encoder(tmp_path):
    assert td.declared_dtype(_prx(tmp_path)) == td.BF16


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/torch_device.py:_NAMED")
def test_a_config_naming_a_full_or_unknown_precision_declares_no_half(tmp_path):
    _config(tmp_path / "text_encoder" / "config.json", torch_dtype="float32", dtype="auto")
    assert td.declared_dtype(tmp_path) == ""


def test_sdxl_turbo_keeps_float16(tmp_path):
    """The model that works at fp16 today must not move off it."""
    root = _sdxl_turbo(tmp_path)
    assert td.declared_dtype(root) == td.FP16
    assert td.load_dtype(td.declared_dtype(root), "mps") == td.FP16
    assert td.load_dtype(td.declared_dtype(root), "cuda") == td.FP16


def test_stored_bf16_weights_declare_bf16_without_any_config(tmp_path):
    _safetensors(tmp_path / "transformer" / "diffusion_pytorch_model-00001-of-00002.safetensors", "BF16")
    assert td.declared_dtype(tmp_path) == td.BF16


def test_bf16_wins_over_fp16_when_components_disagree(tmp_path):
    _safetensors(tmp_path / "vae" / "diffusion_pytorch_model.safetensors", "F16")
    _safetensors(tmp_path / "transformer" / "diffusion_pytorch_model.safetensors", "BF16")
    assert td.declared_dtype(tmp_path) == td.BF16


@pytest.mark.parametrize("root", [None, "missing"])
def test_no_snapshot_declares_nothing(tmp_path, root):
    assert td.declared_dtype(tmp_path / root if root else None) == ""


@pytest.mark.parametrize("body", [
    struct.pack("<Q", 1 << 40),
    struct.pack("<Q", 5) + b"nope!",
    struct.pack("<Q", 2) + b"[]",
    b"\x01",
])
def test_an_unreadable_header_declares_nothing(tmp_path, body):
    (tmp_path / "transformer").mkdir()
    (tmp_path / "transformer" / "w.safetensors").write_bytes(body)
    (tmp_path / "transformer" / "config.json").write_text("[1]", encoding="utf-8")
    assert td.declared_dtype(tmp_path) == ""


def test_an_undeclared_repo_loads_bf16_on_metal_and_fp16_on_cuda():
    assert td.load_dtype("", "mps") == td.BF16
    assert td.load_dtype("", "cuda") == td.FP16


def test_the_declaration_wins_over_the_device_default():
    assert td.load_dtype(td.BF16, "cuda") == td.BF16
    assert td.load_dtype(td.FP16, "mps") == td.FP16


def test_the_cpu_loads_fp32_whatever_the_repo_says():
    assert td.load_dtype(td.BF16, "cpu") == td.FP32


def test_the_video_runner_keeps_its_bf16_default():
    assert td.load_dtype("", "cuda", td.BF16) == td.BF16
    assert td.load_dtype(td.FP16, "cuda", td.BF16) == td.FP16


def test_a_local_directory_is_its_own_snapshot(tmp_path):
    assert image_diffusers.snapshot(str(tmp_path)) == tmp_path


def test_a_one_variant_fetch_still_resolves_to_its_snapshot(monkeypatch, tmp_path):
    """snapshot_download(local_files_only) called sdxl-turbo's variant-only fetch incomplete, so it loaded at bf16."""
    from huggingface_hub import constants
    repo = tmp_path / "models--stabilityai--sdxl-turbo"
    snap = _sdxl_turbo(repo / "snapshots" / "71153311")
    _config(snap / "model_index.json")
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("71153311", encoding="utf-8")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    import huggingface_hub

    def incomplete(*a, **kw):
        raise RuntimeError("The cached snapshot for 'stabilityai/sdxl-turbo' is incomplete: 21 file(s) are missing")
    monkeypatch.setattr(huggingface_hub, "snapshot_download", incomplete)
    assert image_diffusers.snapshot("stabilityai/sdxl-turbo") == snap
    assert td.declared_dtype(image_diffusers.snapshot("stabilityai/sdxl-turbo")) == td.FP16
    assert image_diffusers.snapshot("nobody/absent") is None


# --- 2. the runner retries the other half on a blank canvas ------------------

class _Gen:
    def __init__(self, device):
        self.device = device

    def manual_seed(self, seed):
        self.seed = seed
        return self


_TORCH = SimpleNamespace(Generator=_Gen, mps=SimpleNamespace(empty_cache=lambda: None),
                         cuda=SimpleNamespace(empty_cache=lambda: None))


def _args(**kw):
    return SimpleNamespace(**{"model": "Photoroom/prxpixel-t2i", "prompt": "a fox", "width": 64,
                              "height": 64, "seed": 1, "steps": None, "guidance": None, **kw})


def _drawn():
    im = Image.new("RGB", (64, 64))
    im.putdata([((x * 4) % 256, (y * 4) % 256, 128) for y in range(64) for x in range(64)])
    return im


def _builder(results: dict, calls: list):
    """A pipeline per dtype: an Image renders it, an exception raises from the call."""
    def build(model, device, dtype):
        calls.append(dtype)
        got = results[dtype]

        def pipe(**kw):
            assert kw["generator"].seed == 1
            if isinstance(got, Exception):
                raise got
            return SimpleNamespace(images=[got])
        return pipe
    return build


BLACK = Image.new("RGB", (64, 64), (0, 0, 0))


def test_a_nan_black_image_at_fp16_is_redrawn_at_bf16(capsys):
    calls = []
    image, _, dtype, tried = image_diffusers.render(
        _args(), "cuda", _TORCH, td.FP16, _builder({td.FP16: BLACK, td.BF16: _drawn()}, calls))
    assert (dtype, tried, calls) == (td.BF16, [td.FP16], [td.FP16, td.BF16])
    assert not image_check.blank(image)
    assert "blank image at float16" in capsys.readouterr().err


def test_a_model_that_only_runs_fp16_falls_back_when_bf16_is_refused():
    calls = []
    refused = TypeError("Trying to convert BFloat16 to the MPS backend but it does not have support for that dtype.")
    _, _, dtype, tried = image_diffusers.render(
        _args(), "mps", _TORCH, td.BF16, _builder({td.BF16: refused, td.FP16: _drawn()}, calls))
    assert (dtype, tried) == (td.FP16, [td.BF16])


def test_a_good_first_render_is_not_redrawn():
    calls = []
    _, _, dtype, tried = image_diffusers.render(
        _args(), "mps", _TORCH, td.BF16, _builder({td.BF16: _drawn()}, calls))
    assert (dtype, tried, calls) == (td.BF16, [], [td.BF16])


def test_blank_at_both_halves_returns_the_blank_for_the_check_to_class():
    calls = []
    image, _, dtype, tried = image_diffusers.render(
        _args(), "mps", _TORCH, td.BF16, _builder({td.BF16: BLACK, td.FP16: BLACK}, calls))
    assert (dtype, tried, calls) == (td.FP16, [td.BF16], [td.BF16, td.FP16])
    assert image_check.blank(image)


def test_an_error_that_is_not_about_bf16_is_not_retried():
    calls = []
    with pytest.raises(RuntimeError, match="hidden_states"):
        image_diffusers.render(_args(), "mps", _TORCH, td.BF16,
                               _builder({td.BF16: RuntimeError("name hidden_states"), td.FP16: _drawn()}, calls))
    assert calls == [td.BF16]


def test_the_cpu_draws_once_at_fp32():
    calls = []
    image_diffusers.render(_args(), "cpu", _TORCH, td.FP32, _builder({td.FP32: BLACK}, calls))
    assert calls == [td.FP32]


# --- 3. a blank canvas is not the candidate's failure ------------------------

@pytest.mark.parametrize("fill", [(0, 0, 0), (128, 128, 128), (255, 255, 255)])
def test_a_constant_image_is_blank_output(tmp_path, fill):
    p = tmp_path / "x.png"
    Image.new("RGB", (512, 512), fill).save(p)
    r = image_check.check(p, expect=(512, 512))
    assert not r.ok and r.failure_class == reasons.BLANK_OUTPUT


def test_a_drawn_image_has_no_failure_class(tmp_path):
    p = tmp_path / "x.png"
    _drawn().save(p)
    r = image_check.check(p)
    assert r.ok and r.failure_class == ""


def test_a_wrong_size_is_not_blank_output(tmp_path):
    p = tmp_path / "x.png"
    Image.new("RGB", (64, 64)).save(p)
    assert image_check.check(p, expect=(512, 512)).failure_class == ""


def _black_engine(tmp_path):
    fake = tmp_path / "black.py"
    fake.write_text("import sys\nfrom PIL import Image\n"
                    "out = sys.argv[sys.argv.index('--output') + 1]\n"
                    "Image.new('RGB', (512, 512), (0, 0, 0)).save(out)\n", encoding="utf-8")
    real = engines.resolve(SPEC)
    return dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake), "--output", str(o)])


def test_a_pipeline_that_renders_nan_black_is_declined_runtime_not_broken(tmp_path):
    from evals.runners.process import ProcessRunner
    row = ProcessRunner(_black_engine(tmp_path), tmp_path / "out").run(FOX)
    assert not row.passed and row.failure_class == reasons.BLANK_OUTPUT
    summary = summarize([row])
    key = next(iter(summary))
    v = screen.outcome(0, summary, candidate=SPEC, key=key)
    assert (v.outcome, v.reason, v.failure_class) == ("declined", reasons.RUNTIME, reasons.BLANK_OUTPUT)
    assert v.until.startswith("version:diffusers>")
    assert "blank canvas" in v.detail


def test_a_blank_video_is_blank_output(monkeypatch, tmp_path):
    from harness.checks import video as video_check
    monkeypatch.setattr(video_check, "probe", lambda path: video_check.VideoInfo(64, 64, 9, 1.0))
    monkeypatch.setattr(video_check, "_sample", lambda path: [Image.new("L", (64, 64))])
    p = tmp_path / "v.mp4"
    p.write_bytes(b"x")
    r = video_check.check(p)
    assert not r.ok and r.failure_class == reasons.BLANK_OUTPUT
