"""Generated cases for the ocr, pii and tts lanes: deterministic, attributed, controlled. #603."""
import importlib
import json
import re
from pathlib import Path

import pytest

from evals import core, importers
from evals.core import load_cases, score, summarize
from harness import holdout, privacy

ROOT = Path(__file__).resolve().parents[1]
GENERATORS = ("ocr_synth", "pii_synth", "tts_synth")
#: #595: about 132 holdout cases give power 0.8 at +0.20 when a case is the unit.
HOLDOUT_TARGET = 130


def _mod(name):
    return importlib.import_module(f"evals.importers.{name}")


@pytest.fixture(scope="module", params=GENERATORS)
def gen(request):
    return request.param, _mod(request.param)


@pytest.fixture(scope="module")
def committed():
    """Each generator's committed cases, loaded once."""
    return {name: load_cases(importers.CASES / _mod(name).LANE / name) for name in GENERATORS}


def _rows(cases, answer_for, wrap=lambda a: a):
    rows = []
    for c in cases:
        r = score(c, wrap(answer_for(c)))
        r.candidate = "stub"
        rows.append(r)
    return summarize(rows)["stub"]


def _case(mod, row):
    """The case dict a row becomes, without rendering any image."""
    return mod.case_of(row) if hasattr(mod, "case_of") else mod.convert(row).case


# --- the shared shape ------------------------------------------------------

def test_every_generator_is_a_registered_source_in_its_lane():
    for name in GENERATORS:
        assert importers.Source(name, _mod(name).LANE) in importers.REGISTRY


def test_a_generator_writes_the_same_bytes_twice(gen, tmp_path):
    name, mod = gen
    one, two = tmp_path / "a", tmp_path / "b"
    importers.run(name, root=one, rows=mod.fetch(count=12))
    importers.run(name, root=two, rows=mod.fetch(count=12))
    files = sorted(p.relative_to(one) for p in one.rglob("*") if p.is_file())
    assert files and files == sorted(p.relative_to(two) for p in two.rglob("*") if p.is_file())
    for f in files:
        assert (one / f).read_bytes() == (two / f).read_bytes(), f
    assert len(load_cases(one / mod.LANE / name)) == 12


def test_another_seed_draws_other_cases(gen):
    _, mod = gen
    a = [(_case(mod, r)["prompt"], _case(mod, r)["assert"]) for r in mod.fetch(count=12)]
    b = [(_case(mod, r)["prompt"], _case(mod, r)["assert"])
         for r in mod.fetch(seed=mod.SEED + 1, count=12)]
    assert a != b


def test_every_case_is_attributed_to_the_generator_version_and_seed(gen):
    _, mod = gen
    assert len(mod.REVISION) == 40 and mod.LICENSE in importers.ALLOWED_LICENSES
    assert f"v{mod.VERSION} seed {mod.SEED}" in mod.SOURCE
    for row in mod.fetch(count=12):
        att = _case(mod, row)["attribution"]
        assert att["importer"] == mod.__name__ and att["revision"] == mod.REVISION
        assert att["version"] == mod.VERSION and att["seed"] == mod.SEED
        assert att["item"] == str(row["item"]) and att["license"] and att["transform"]


def test_the_committed_cases_are_what_the_generator_writes(gen):
    """A reference is never typed by hand: the committed yaml is the generator's, byte for byte."""
    name, mod = gen
    want = {}
    for row in mod.fetch():
        case = _case(mod, row)
        want[f"{case['id']}.yaml"] = importers._dump(mod, case)
    out = importers.CASES / mod.LANE / name
    have = {p.name: p.read_text(encoding="utf-8") for p in out.glob("*.yaml")}
    assert set(have) == set(want)
    for fname, text in want.items():
        assert have[fname] == text, fname


def test_an_imported_file_is_written_beside_its_case_and_may_not_escape(tmp_path):
    mod = _mod("ocr_synth")
    row = mod.fetch(count=1)[0]
    made = mod.convert(row)
    importers.write(mod, "ocr_synth", [made], tmp_path)
    (case,) = load_cases(tmp_path / "ocr" / "ocr_synth")
    assert case.input_file.read_bytes() == made.files[0][1]
    bad = importers.Imported(made.case, files=(("../escape.png", b"x"),))
    with pytest.raises(ValueError, match="outside"):
        importers.write(mod, "ocr_synth", [bad], tmp_path)


@pytest.mark.parametrize("name,want", [
    ("ocr_synth", {"reference": 440, "other-case": 0, "empty": 0}),
    ("pii_synth", {"reference": 540, "nothing": 120, "everything": 0}),
    ("tts_synth", {"reference": 420, "silence": 0, "fixed": 0}),
])
def test_the_registered_negative_control_separates_reference_from_responders(committed, name,
                                                                              want):
    mod = _mod(name)
    got = importers.negative_control(committed[name], mod.RESPONDERS, mod.passes)
    assert {k: v[0] for k, v in got.items()} == want
    assert {v[1] for v in got.values()} == {len(committed[name])}


def test_prompts_are_unique_within_a_lane(committed):
    for name, cases in committed.items():
        lane = load_cases(ROOT / "evals" / "cases" / cases[0].modality)
        keys = [(c.prompt, json.dumps(c.assertions, sort_keys=True)) for c in lane]
        assert len(keys) == len(set(keys)), name


def test_each_lane_reaches_the_holdout_target(committed):
    for name, cases in committed.items():
        lane = cases[0].modality
        split = holdout.assign(lane, load_cases(ROOT / "evals" / "cases" / lane))
        assert len(split.holdout) >= HOLDOUT_TARGET, (lane, len(split.holdout))


def test_the_generated_text_passes_the_privacy_scanner(committed):
    for cases in committed.values():
        for c in cases:
            found = privacy.scan(c.source.read_text(encoding="utf-8"), str(c.source))
            assert not found, found


def _prov(c):
    import yaml
    return yaml.safe_load(c.source.read_text(encoding="utf-8"))["attribution"]


# --- ocr -------------------------------------------------------------------

def test_ocr_cases_vary_style_and_kind_and_images_stay_small(committed):
    cases = committed["ocr_synth"]
    styles = {_prov(c)["style"] for c in cases}
    kinds = {_prov(c)["kind"] for c in cases}
    assert len(styles) >= 6 and len(kinds) >= 6
    assert {_prov(c)["degrade"] for c in cases} == set(_mod("ocr_synth").DEGRADE)
    assert any("\n" in c.assertions["text"] for c in cases)
    sizes = [c.input_file.stat().st_size for c in cases]
    assert max(sizes) < 40_000 and sum(sizes) < 4_000_000


def test_ocr_negative_control_another_cases_text_scores_clearly_worse(committed):
    cases = committed["ocr_synth"]
    ref = [c.assertions["text"] for c in cases]
    right = _rows(cases, lambda c: c.assertions["text"])
    wrong = _rows(cases, lambda c: ref[(cases.index(c) + 1) % len(cases)])
    assert right["passed"] == len(cases) and right["metrics"]["cer"] == 0.0
    assert wrong["passed"] == 0 and wrong["metrics"]["cer"] > 0.5


@pytest.mark.usefixtures("real_ocr")
def test_the_os_reader_reads_a_sample_of_the_generated_images(committed):
    """Positive control: a working OCR reads them, so a candidate's miss is its own."""
    from harness.checks import ocr
    if ocr.available_backend() is None:
        pytest.skip("no OCR backend on this machine")
    clean = [c for c in committed["ocr_synth"] if _prov(c)["degrade"] == "none"][::8]
    rows = _rows(clean, lambda c: "\n".join(ocr.read(c.input_file)))
    assert len(clean) >= 8 and rows["metrics"]["cer"] < 0.1


# --- pii -------------------------------------------------------------------

def _kinds(c):
    return _prov(c)["kinds"]


def test_pii_cases_cover_every_kind_and_sentences_without_any(committed):
    cases = committed["pii_synth"]
    kinds = set()
    for c in cases:
        assert len(_kinds(c)) == len(c.assertions["pii"])
        kinds |= set(_kinds(c))
    assert {"name", "email", "phone", "address", "key", "iban", "card", "ip"} <= kinds
    none = [c for c in cases if not c.assertions["pii"]]
    assert 0.1 * len(cases) < len(none) < 0.4 * len(cases)


def test_pii_values_are_clearly_fake(committed):
    from evals.importers import pii_synth
    fake = (set(pii_synth.IBANS) | set(pii_synth.CARDS)
            | {f"192.0.2.{i}" for i in range(256)} | {f"198.51.100.{i}" for i in range(256)}
            | {f"203.0.113.{i}" for i in range(256)})
    for c in committed["pii_synth"]:
        for label, kind in zip(c.assertions["pii"], _kinds(c)):
            if kind == "email":
                assert label.rsplit("@", 1)[1] in pii_synth.EMAIL_DOMAINS
            elif kind == "phone":
                assert re.search(r"555[- ]01\d\d$", label), label
            elif kind in ("iban", "card", "ip"):
                assert label in fake
            elif kind == "key":
                assert label.startswith(pii_synth.KEY_PREFIX)


def test_pii_negative_controls_mark_nothing_and_mark_everything(committed):
    cases = committed["pii_synth"]
    wrap = lambda spans: json.dumps({"spans": spans})  # noqa: E731
    right = _rows(cases, lambda c: [[s, e] for s, e in c.params["spans"]], wrap)
    nothing = _rows(cases, lambda c: [], wrap)
    everything = _rows(cases, lambda c: [[0, len(c.prompt)]], wrap)
    none = sum(1 for c in cases if not c.assertions["pii"])
    assert right["passed"] == len(cases) and right["metrics"]["pii_f1"] == 1.0
    assert nothing["metrics"].get("pii_f1", 0.0) == 0.0 and nothing["passed"] == none
    assert everything["metrics"]["pii_f1"] < 0.6 and everything["passed"] == 0


# --- tts -------------------------------------------------------------------

def _heard(cases, tmp_path, transcript_for):
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"\0" * 9000)
    rows = []
    for c in cases:
        out = core.CHECKERS["tts"](wav, c, transcriber=lambda p, c=c: transcript_for(c))
        rows.append(out)
    errors = sum(o.metrics["wer_errors"] for o in rows)
    words = sum(o.metrics["wer_words"] for o in rows)
    return sum(1 for o in rows if o.ok), errors / words


def test_tts_negative_controls_silence_and_a_fixed_sentence(committed, tmp_path):
    cases = committed["tts_synth"]
    assert all(c.language == "en" for c in cases)
    passed, rate = _heard(cases, tmp_path, lambda c: c.prompt)
    assert passed == len(cases) and rate == 0.0
    passed, rate = _heard(cases, tmp_path, lambda c: "")
    assert passed == 0 and rate == 1.0
    fixed = _mod("tts_synth").RESPONDERS["fixed"](cases[0])
    passed, rate = _heard(cases, tmp_path, lambda c: fixed)
    # Sentences sharing a template, a name and a city differ in two words and may still pass.
    assert passed <= 0.02 * len(cases) and rate > 0.6


def test_tts_numbers_avoid_the_normalizer_ambiguities(committed):
    """num2words says 'one hundred and five' where a voice says 'one hundred five'."""
    for c in committed["tts_synth"]:
        for n in re.findall(r"\d+", c.prompt):
            assert 2 <= int(n) <= 99, c.prompt


def test_every_degradation_has_a_strength_and_an_unknown_one_is_refused():
    from PIL import Image
    ocr_synth = _mod("ocr_synth")
    assert set(ocr_synth.STRENGTH) == set(ocr_synth.DEGRADE) - {"none"}
    with pytest.raises(ValueError, match="degradation"):
        ocr_synth._degrade(Image.new("L", (4, 4), 255), "fog", 1, 255)
