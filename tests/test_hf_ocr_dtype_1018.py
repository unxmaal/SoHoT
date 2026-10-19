"""An hf-ocr model loads at the dtype its snapshot declares, not fp16 for every repo, and says which. #1018."""
import dataclasses
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from evals.core import load_cases
from harness import engines, hf_task
from harness import torch_device as td

ROOT = Path(__file__).resolve().parents[1]
CASE = next(c for c in load_cases(ROOT / "evals" / "cases" / "ocr") if c.id == "ocr-invoice-line")


def _repo(root: Path, **config) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def _paddle(root: Path) -> Path:
    """PaddleOCR-VL-1.6 as the Studio fetched it: config and vision config name bfloat16."""
    return _repo(root, model_type="paddleocr_vl", torch_dtype="bfloat16",
                 vision_config={"torch_dtype": "bfloat16"})


def _trocr(root: Path) -> Path:
    """microsoft/trocr-small-printed: float32 at the top, null in the sub-configs."""
    return _repo(root, model_type="vision-encoder-decoder", torch_dtype="float32",
                 encoder={"torch_dtype": None}, decoder={"torch_dtype": None})


@pytest.mark.parametrize("device", ["mps", "cuda"])
def test_a_repo_that_declares_bf16_loads_at_bf16_on_an_accelerator(tmp_path, device):
    assert hf_task.model_dtype(str(_paddle(tmp_path / "p")), device) == td.BF16


@pytest.mark.parametrize("device", ["mps", "cuda"])
def test_a_repo_that_declares_no_half_keeps_fp16_on_an_accelerator(tmp_path, device):
    assert hf_task.model_dtype(str(_trocr(tmp_path / "t")), device) == td.FP16
    assert hf_task.model_dtype("nobody/absent", device) == td.FP16


def test_the_cpu_loads_fp32_whatever_the_repo_or_the_spec_says(tmp_path):
    paddle = str(_paddle(tmp_path / "p"))
    assert hf_task.model_dtype(paddle, "cpu") == td.FP32
    assert hf_task.model_dtype(paddle, "cpu", forced=td.FP16) == td.FP32


def test_a_forced_dtype_wins_over_the_declaration_on_an_accelerator(tmp_path):
    paddle = str(_paddle(tmp_path / "p"))
    assert hf_task.model_dtype(paddle, "mps", forced=td.FP16) == td.FP16
    assert hf_task.model_dtype(paddle, "mps", forced=td.FP32) == td.FP32


def test_a_cached_repo_id_resolves_to_its_snapshot_at_the_revision_asked(monkeypatch, tmp_path):
    from huggingface_hub import constants
    repo = tmp_path / "models--PaddlePaddle--PaddleOCR-VL-1.6"
    _paddle(repo / "snapshots" / "c5630abae1")
    _trocr(repo / "snapshots" / "0ld")
    (repo / "refs").mkdir()
    (repo / "refs" / "main").write_text("c5630abae1", encoding="utf-8")
    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    name = "PaddlePaddle/PaddleOCR-VL-1.6"
    assert td.snapshot(name) == repo / "snapshots" / "c5630abae1"
    assert hf_task.model_dtype(name, "mps") == td.BF16
    assert hf_task.model_dtype(name, "mps", revision="0ld") == td.FP16


class _Net:
    def __init__(self, seen):
        self.seen = seen
        self.config = SimpleNamespace(_attn_implementation="eager")

    def to(self, dev):
        self.seen["to"] = dev
        return self

    def generate(self, pixel_values=None, max_new_tokens=0, do_sample=False):
        self.seen["pixels"] = pixel_values
        return SimpleNamespace(shape=(1, 4))


class _Pixels:
    def to(self, dev, dtype=None):
        return (dev, dtype)


def _fake_stack(monkeypatch, seen):
    """torch, PIL and transformers as read_image touches them, for an encoder-decoder repo."""
    torch = ModuleType("torch")
    torch.bfloat16, torch.float16, torch.float32 = "T.bf16", "T.fp16", "T.fp32"
    transformers = ModuleType("transformers")

    def from_pretrained(model, revision=None, dtype=None, **kw):
        seen["dtype"] = dtype
        return _Net(seen)
    transformers.AutoModelForImageTextToText = SimpleNamespace(from_pretrained=from_pretrained)
    proc = SimpleNamespace(chat_template=None,
                           image_processor=lambda images, return_tensors: SimpleNamespace(pixel_values=_Pixels()),
                           tokenizer=SimpleNamespace(batch_decode=lambda out, skip_special_tokens: ["Invoice"]))
    transformers.AutoProcessor = SimpleNamespace(from_pretrained=lambda *a, **kw: proc)
    transformers.AutoTokenizer = None
    pil = ModuleType("PIL")
    pil.Image = SimpleNamespace(open=lambda p: SimpleNamespace(convert=lambda mode: "picture"))
    for name, mod in (("torch", torch), ("transformers", transformers), ("PIL", pil)):
        monkeypatch.setitem(sys.modules, name, mod)


def test_read_image_loads_and_feeds_the_model_at_the_declared_dtype_and_records_it(monkeypatch, tmp_path):
    seen: dict = {}
    _fake_stack(monkeypatch, seen)
    runtime: dict = {}
    got = hf_task.read_image(str(_paddle(tmp_path / "p")), "i.png", "", device="mps", runtime=runtime)
    assert got == "Invoice"
    assert seen["dtype"] == "T.bf16"
    assert seen["pixels"] == ("mps", "T.bf16")
    assert runtime["dtype"] == td.BF16 and runtime["device"] == "mps"


def test_read_image_on_the_cpu_fallback_records_fp32(monkeypatch, tmp_path):
    seen: dict = {}
    _fake_stack(monkeypatch, seen)
    runtime: dict = {}
    hf_task.read_image(str(_paddle(tmp_path / "p")), "i.png", "", device="cpu", runtime=runtime)
    assert seen["dtype"] == "T.fp32" and runtime["dtype"] == td.FP32


def test_the_cli_passes_a_forced_dtype_and_the_runtime_file_names_the_dtype(tmp_path, monkeypatch):
    got = {}

    def fake_read(model, image, prompt, *, revision=None, max_new_tokens=512,
                  device=None, attn="", runtime=None, dtype=""):
        got["dtype"] = dtype
        runtime.update(device="mps", attn="eager", dtype=dtype or td.BF16)
        return "Invoice #4471"
    monkeypatch.setattr(hf_task, "read_image", fake_read)
    out = tmp_path / "o.txt"
    assert hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(out),
                         "--dtype", "float16", "--one-attempt"]) == 0
    assert got == {"dtype": "float16"}
    assert json.loads(Path(hf_task.runtime_path(out)).read_text(encoding="utf-8"))["dtype"] == "float16"
    with pytest.raises(SystemExit):
        hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(out), "--dtype", "int8"])


def test_an_hf_ocr_spec_can_pin_a_dtype_as_its_own_candidate(tmp_path):
    pinned = engines.resolve("hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6,dtype=float16")
    plain = engines.resolve("hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6")
    assert pinned.name != plain.name
    argv = pinned.argv("", tmp_path / "o.txt", {"input": "i.png"})
    assert argv[argv.index("--dtype") + 1] == "float16"
    assert "--dtype" not in plain.argv("", tmp_path / "o.txt", {"input": "i.png"})
    with pytest.raises(ValueError, match="dtype"):
        engines.resolve("hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6,dtype=int8")


def test_the_runner_puts_the_dtype_that_answered_on_its_row(tmp_path):
    from evals.runners.process import ProcessRunner
    fake = tmp_path / "ok.py"
    fake.write_text(
        "import json, sys\nopen(sys.argv[1], 'w').write('Invoice #4471 due 2026-11-30')\n"
        f"open(sys.argv[1] + {hf_task.RUNTIME_SUFFIX!r}, 'w').write("
        "json.dumps({'device': 'mps', 'attn': 'eager', 'dtype': 'bfloat16'}))\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [sys.executable, str(fake), str(o)])
    r = ProcessRunner(eng, tmp_path / "out").run(CASE)
    assert r.runtime == {"device": "mps", "attn": "eager", "dtype": "bfloat16"}
