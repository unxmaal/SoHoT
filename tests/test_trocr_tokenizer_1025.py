"""trocr's decoder tokenizer: transformers 5 converts its sentencepiece model through protobuf, else falls to tiktoken. #1025."""
import json
import re
import sys
from pathlib import Path

import pytest

from harness import hf_task, reasons, runner_gaps

ROOT = Path(__file__).resolve().parents[1]
#: What transformers 5.17 raised building trocr's decoder in a venv without protobuf.
TIKTOKEN_FALLBACK = "`tiktoken` is required to read a `tiktoken` file. Install it with `pip install tiktoken`."
AUTO_FAILED = ("Couldn't instantiate the backend tokenizer ... You need to have sentencepiece or "
               "tiktoken installed to convert a slow tokenizer to a fast one.")
#: microsoft/trocr-small-printed's own tokenizer files, beside a sentencepiece model trained here.
TROCR_TOKENIZER_CONFIG = {"bos_token": "<s>", "eos_token": "</s>", "unk_token": "<unk>", "sep_token": "</s>",
                          "cls_token": "<s>", "pad_token": "<pad>", "sp_model_kwargs": {},
                          "mask_token": {"content": "<mask>", "single_word": False, "lstrip": True,
                                         "rstrip": False, "normalized": True, "__type": "AddedToken"},
                          "tokenizer_class": "XLMRobertaTokenizer"}
TEXT = "INVOICE #4471 Total: $1,284.50"


def _raise_the_fallback(*_):
    try:
        raise ModuleNotFoundError("No module named 'tiktoken'", name="tiktoken")
    except ModuleNotFoundError:
        raise ValueError(TIKTOKEN_FALLBACK)


def _fallback_error() -> ValueError:
    try:
        _raise_the_fallback()
    except ValueError as exc:
        return exc


class _Auto:
    @staticmethod
    def from_pretrained(model, revision=None):
        raise ValueError(AUTO_FAILED)


def _raises(exc):
    def named(model, revision, first):
        raise exc
    return named


def test_without_protobuf_the_decoder_names_protobuf_not_tiktoken(monkeypatch):
    monkeypatch.setattr(hf_task, "_named_tokenizer", _raise_the_fallback)
    monkeypatch.setitem(sys.modules, "google.protobuf", None)
    with pytest.raises(ModuleNotFoundError) as got:
        hf_task._tokenizer("microsoft/trocr-small-printed", None, _Auto)
    assert got.value.name == "google.protobuf"


def test_with_sentencepiece_and_protobuf_a_tiktoken_repo_names_tiktoken(monkeypatch):
    pytest.importorskip("sentencepiece")
    pytest.importorskip("google.protobuf")
    monkeypatch.setattr(hf_task, "_named_tokenizer", _raise_the_fallback)
    with pytest.raises(ModuleNotFoundError) as got:
        hf_task._tokenizer("m/x", None, _Auto)
    assert got.value.name == "tiktoken"


def test_a_tokenizer_error_that_is_no_conversion_blames_no_package(monkeypatch):
    monkeypatch.setattr(hf_task, "_named_tokenizer", _raises(ValueError("bad special token")))
    monkeypatch.setitem(sys.modules, "google.protobuf", None)

    class Auto:
        @staticmethod
        def from_pretrained(model, revision=None):
            raise ValueError("bad special token")
    with pytest.raises(ValueError, match="bad special token"):
        hf_task._tokenizer("m/x", None, Auto)


@pytest.mark.parametrize("error, dist", [
    (ModuleNotFoundError("No module named 'google.protobuf'", name="google.protobuf"), "protobuf"),
    (_fallback_error(), "tiktoken"),
])
def test_a_venv_gap_exits_4_and_screens_as_a_runtime_gap_the_venv_can_meet(tmp_path, capsys, error, dist):
    def read(model, image, prompt):
        raise error
    rc = hf_task.main(["ocr", "--model", "microsoft/trocr-small-printed", "--image", "i.png",
                       "--out", str(tmp_path / "o.txt")], read=read)
    last = capsys.readouterr().err.strip().splitlines()[-1]
    detail = f"exit {rc}: {last}"
    candidate = "hf-ocr:microsoft/trocr-small-printed"
    assert rc == hf_task.MISSING_PACKAGE
    assert reasons.classify(detail, candidate=candidate) == reasons.MISSING_PACKAGE
    assert reasons.CLASSES[reasons.MISSING_PACKAGE] == ("declined", reasons.RUNTIME)
    assert runner_gaps.cause_until(reasons.MISSING_PACKAGE, detail, candidate) == f"package:{dist}@hf-task"


def test_a_value_error_with_no_import_under_it_still_raises(tmp_path):
    def read(model, image, prompt):
        raise ValueError("the image is empty")
    with pytest.raises(ValueError, match="the image is empty"):
        hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out", str(tmp_path / "o.txt")],
                     read=read)


@pytest.mark.parametrize("script", ["hf-task-venv", "diffusers-venv"])
def test_each_transformers_venv_installs_the_sentencepiece_converters_pair(script):
    pins = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert re.search(r'^PROTOBUF_PIN="protobuf==\d+\.\d+\.\d+"$', pins, re.M)
    venv = (ROOT / "scripts" / f"{script}.sh").read_text(encoding="utf-8")
    assert '"$SENTENCEPIECE_PIN"' in venv and '"$PROTOBUF_PIN"' in venv


def _trocr_shaped_repo(root: Path) -> Path:
    spm = pytest.importorskip("sentencepiece")
    corpus = root / "corpus.txt"
    corpus.write_text("\n".join([TEXT, "Subtotal 1,180.00 Tax 104.50", "Due on receipt"] * 20),
                      encoding="utf-8")
    repo = root / "trocr"
    repo.mkdir()
    spm.SentencePieceTrainer.train(input=str(corpus), model_prefix=str(repo / "sentencepiece.bpe"),
                                   vocab_size=80, model_type="bpe", character_coverage=1.0,
                                   minloglevel=2)
    (repo / "tokenizer_config.json").write_text(json.dumps(TROCR_TOKENIZER_CONFIG), encoding="utf-8")
    (repo / "config.json").write_text(json.dumps({"model_type": "vision-encoder-decoder"}),
                                      encoding="utf-8")
    return repo


def test_a_trocr_shaped_decoder_builds_from_its_sentencepiece_model_and_round_trips(tmp_path):
    pytest.importorskip("google.protobuf")
    transformers = pytest.importorskip("transformers")
    tok = hf_task._tokenizer(str(_trocr_shaped_repo(tmp_path)), None, transformers.AutoTokenizer)
    ids = tok(TEXT)["input_ids"]
    assert tok.decode(ids, skip_special_tokens=True) == TEXT


def test_a_trocr_shaped_decoder_without_protobuf_names_protobuf(tmp_path, monkeypatch):
    transformers = pytest.importorskip("transformers")
    repo = _trocr_shaped_repo(tmp_path)
    convert_slow_tokenizer = pytest.importorskip("transformers.convert_slow_tokenizer")
    import_utils = pytest.importorskip("transformers.utils.import_utils")
    _, why = import_utils.BACKENDS_MAPPING["protobuf"]
    monkeypatch.setitem(import_utils.BACKENDS_MAPPING, "protobuf", (lambda: False, why))
    monkeypatch.setattr(convert_slow_tokenizer, "is_protobuf_available", lambda: False)
    monkeypatch.setitem(sys.modules, "google.protobuf", None)
    with pytest.raises(ModuleNotFoundError) as got:
        hf_task._tokenizer(str(repo), None, transformers.AutoTokenizer)
    assert got.value.name == "google.protobuf"
