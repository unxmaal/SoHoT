"""The ocr lane: transcribe a rendered image, scored on character error rate. #562."""
import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals import core, run  # noqa: E402
from evals.core import Case, load_cases, score, summarize  # noqa: E402
from harness import discover, engines, inspect as ins, lanes, rank, reasons, screen  # noqa: E402
from harness.checks import ocr  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _load():
    here = ROOT / "evals" / "cases" / "ocr"
    try:
        # The hand-rendered fixtures; generated sets are tested in test_generated_cases.
        return [c for c in load_cases(here) if c.source.parent == here]
    except ValueError:
        return []


CASES = _load()
RECURRING = ("PaddlePaddle/PaddleOCR-VL-1.6", "baidu/Unlimited-OCR",
             "JustANormalTinkerer/hayai-ocr-v2")


# --- the lane --------------------------------------------------------------

def test_ocr_is_wanted_after_the_lanes_eric_ranked():
    assert lanes.WANTED.index("ocr") > lanes.WANTED.index("agent")
    assert lanes.known("ocr") and not lanes.human_judged("ocr")


# --- routing ---------------------------------------------------------------

@pytest.mark.parametrize("repo", RECURRING)
def test_each_recurring_ocr_model_routes_to_the_ocr_lane(repo):
    import fakes
    assert ins.lane_and_source(fakes.card(repo)) == ("ocr", "tag")


@pytest.mark.parametrize("task,tags,lane", [
    # A captioner reads an image and is not OCR: the case's reference is text in the image.
    ("image-to-text", ["image-captioning"], ""),
    ("image-text-to-text", ["vision-language", "qwen3_5"], "code"),
    # A card naming another lane by tag keeps it.
    ("image-text-to-text", ["svg", "ocr"], "svg"),
    # A text model tagged ocr is not stolen from code: it reads no image.
    ("text-generation", ["ocr"], "code"),
])
def test_ocr_routing_steals_nothing_from_other_lanes(task, tags, lane):
    assert ins.lane_for({"pipeline_tag": task, "tags": tags}) == lane


def test_a_recorded_captioner_card_stays_laneless():
    import fakes
    assert ins.lane_for(fakes.card("Salesforce/blip-image-captioning-base")) == ""


@pytest.mark.parametrize("repo", RECURRING)
def test_each_recurring_ocr_model_is_reachable_by_an_ocr_query(repo):
    """RULE #462: HF search matches a substring of the repo id."""
    queries = [q.lower() for q in discover.lane_queries("ocr")]
    assert any(q in repo.lower() for q in queries), queries


def test_the_ocr_lane_has_a_measure_command():
    assert "--modality ocr" in discover._HOW["ocr"]


# --- the cases -------------------------------------------------------------

def test_the_lane_has_enough_committed_cases_each_with_an_image_and_a_reference():
    assert len(CASES) >= 6
    for c in CASES:
        assert c.modality == "ocr"
        assert c.input_file and c.input_file.is_file() and c.input_file.suffix == ".png"
        assert c.assertions["text"].strip()


def test_the_committed_images_are_what_the_generator_renders(tmp_path):
    """The fixtures are the generator's output, so a reference is never typed by hand."""
    from evals import ocr_corpus
    ocr_corpus.write(tmp_path)
    fresh = {c.id: c for c in load_cases(tmp_path)}
    for c in CASES:
        assert fresh[c.id].assertions == c.assertions
        assert fresh[c.id].prompt == c.prompt


def test_an_image_change_changes_the_case_digest(tmp_path):
    from PIL import Image
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (4, 4), "white").save(a)
    Image.new("RGB", (4, 4), "black").save(b)
    one = Case(id="x", modality="ocr", prompt="p", input_file=a, assertions={"text": "t"})
    two = dataclasses.replace(one, input_file=b)
    assert core.case_digest(one) != core.case_digest(two)


def test_an_ocr_case_without_an_input_file_is_refused(tmp_path):
    (tmp_path / "c.yaml").write_text("id: c\nmodality: ocr\nprompt: p\nassert: {text: t}\n",
                                     encoding="utf-8")
    with pytest.raises(ValueError, match="input_file"):
        load_cases(tmp_path)


def test_an_ocr_case_without_a_reference_is_refused(tmp_path):
    (tmp_path / "i.png").write_bytes(b"x")
    (tmp_path / "c.yaml").write_text("id: c\nmodality: ocr\nprompt: p\n"
                                     "input_file: i.png\n", encoding="utf-8")
    with pytest.raises(ValueError, match="assert.text"):
        load_cases(tmp_path)


# --- the metric and its negative control -----------------------------------

def _rows(answer_for):
    rows = []
    for c in CASES:
        r = score(c, answer_for(c))
        r.candidate = "stub"
        rows.append(r)
    return rows


def test_a_right_transcription_passes_with_zero_cer():
    rows = _rows(lambda c: c.assertions["text"])
    assert all(r.passed for r in rows)
    assert summarize(rows)["stub"]["metrics"]["cer"] == 0.0


def test_negative_control_a_wrong_transcriber_scores_clearly_worse():
    """Gauntlet: a metric quoted without a negative control. Each case is handed
    the NEXT case's reference, which is real text that is not in the image."""
    order = [c.id for c in CASES]
    ref = {c.id: c.assertions["text"] for c in CASES}
    wrong = _rows(lambda c: ref[order[(order.index(c.id) + 1) % len(order)]])
    right = _rows(lambda c: ref[c.id])
    w = summarize(wrong)["stub"]
    assert w["passed"] == 0
    assert w["metrics"]["cer"] > 0.5 > summarize(right)["stub"]["metrics"]["cer"]


def test_layout_whitespace_is_not_an_error_but_case_and_characters_are():
    assert ocr.text_cer("a b\nc", "a  b c") == (0, 5)
    errors, chars = ocr.text_cer("Invoice #4471", "invoice #4471")
    assert errors == 1 and chars == 13


def test_an_empty_transcription_is_a_total_miss():
    c = CASES[0]
    r = score(c, "")
    assert not r.passed and r.metrics["cer"] == 1.0


def test_corpus_cer_is_pooled_over_characters_not_averaged_over_cases():
    a = Case(id="a", modality="ocr", prompt="p", assertions={"text": "ab"})
    b = Case(id="b", modality="ocr", prompt="p", assertions={"text": "abcdefghij"})
    rows = [score(a, "xb"), score(b, "abcdefghij")]
    for r in rows:
        r.candidate = "s"
    assert summarize(rows)["s"]["metrics"]["cer"] == round(1 / 12, 4)


def test_the_os_reader_reads_the_committed_images():
    """Positive control on the fixtures: a working OCR reads them, so a miss is the candidate's."""
    if ocr.available_backend() is None:
        pytest.skip("no OCR backend on this machine")
    rows = []
    for c in CASES:
        got = "\n".join(ocr.read(c.input_file))
        r = score(c, got)
        r.candidate = "os"
        rows.append(r)
    assert summarize(rows)["os"]["metrics"]["cer"] < 0.1


# --- engines and the runner ------------------------------------------------

def test_the_os_reader_is_a_process_engine_in_the_ocr_lane(tmp_path):
    e = engines.resolve("osocr:auto")
    assert e.modality == "ocr" and e.output_suffix == ".txt"
    argv = e.argv("p", tmp_path / "o.txt", {"input": "/x/i.png"})
    assert argv[-3:] == ["auto", "/x/i.png", str(tmp_path / "o.txt")]
    with pytest.raises(ValueError, match="backend"):
        engines.resolve("osocr:tesseract")


def test_a_transformers_ocr_model_is_a_process_engine(tmp_path):
    e = engines.resolve("hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6,prompt=OCR:")
    assert e.modality == "ocr"
    argv = e.argv("Transcribe", tmp_path / "o.txt", {"input": "/x/i.png"})
    assert argv[1] == "ocr"
    assert argv[argv.index("--model") + 1] == "PaddlePaddle/PaddleOCR-VL-1.6"
    assert argv[argv.index("--image") + 1] == "/x/i.png"
    assert argv[argv.index("--prompt") + 1] == "OCR:"
    with pytest.raises(ValueError, match="needs a model"):
        engines.resolve("hf-ocr:")
    with pytest.raises(ValueError, match="no input image"):
        e.argv("p", tmp_path / "o.txt", {})


def test_the_lane_spells_a_discovered_model_for_the_transformers_engine():
    assert screen.candidate_for("ocr", "someorg/a-model") == "hf-ocr:someorg/a-model"
    assert not screen.no_runner("hf-ocr:someorg/a-model")
    assert screen.candidate_for("ocr", "osocr:auto") == "osocr:auto"


def test_run_selects_only_ocr_cases_for_an_ocr_engine():
    assert run.modality_of("hf-ocr:a/b") == "ocr"
    mixed = [Case(id="o", modality="ocr", prompt="p"), Case(id="c", modality="code", prompt="p")]
    assert [c.id for c in run.cases_for("osocr:auto", mixed)] == ["o"]
    # A text candidate reads no image, so it is never handed one.
    assert "o" not in [c.id for c in run.cases_for("q3-4b", mixed)]


def test_the_typed_default_and_family_name_the_os_reader():
    from harness import cli, verify, winners
    assert winners.typed()["ocr"] == cli.DEFAULT_OCR_ENGINE == "osocr:auto"
    assert winners.FAMILIES["ocr"] == "engine"
    assert verify.COST_S["ocr"] > 0


def test_an_ocr_run_through_the_process_runner_is_scored(tmp_path):
    """A fake reader stands in for the venv; the input path reaches it and the row scores."""
    from evals.runners.process import ProcessRunner
    fake = tmp_path / "fake_ocr.py"
    fake.write_text(
        "import sys\na = sys.argv\n"
        "img = a[a.index('--image') + 1]\nout = a[a.index('--out') + 1]\n"
        "open(out, 'w', encoding='utf-8').write('OPEN 24 HOURS' if img.endswith('sign-open.png') "
        "else 'nothing')\n", encoding="utf-8")
    real = engines.resolve("hf-ocr:someorg/a-model")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [
        sys.executable, str(fake), *real.argv(p, o, params)[1:]])
    sign = next(c for c in CASES if c.id == "ocr-sign-open")
    r = ProcessRunner(eng, tmp_path / "out").run(sign)
    assert r.passed and r.metrics["cer"] == 0.0, r.detail


# --- the script that runs in the transformers venv -------------------------

@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:HF_TASK_BIN")
def test_the_engines_argv_is_what_the_script_it_names_accepts(monkeypatch, tmp_path):
    """Both halves of the seam: the default binary runs hf_task, and hf_task parses the argv."""
    from harness import hf_task
    monkeypatch.delenv("HF_TASK_BIN", raising=False)
    argv = engines.resolve("hf-ocr:m/x,max_new_tokens=64").argv(
        "p", tmp_path / "o.txt", {"input": str(tmp_path / "i.png")})
    script = Path(argv[0])
    assert script == ROOT / "scripts" / "hf-task.sh"
    text = script.read_text(encoding="utf-8")
    assert "-m harness.hf_task" in text and "hf-task-venv.sh" in text
    seen = {}

    def read(model, image, prompt):
        seen.update(model=model, image=image, prompt=prompt)
        return "x"
    assert hf_task.main(argv[1:], read=read) == 0
    assert seen == {"model": "m/x", "image": str(tmp_path / "i.png"), "prompt": "p"}

def test_the_transformers_script_writes_what_the_model_read(tmp_path):
    from harness import hf_task
    out = tmp_path / "o.txt"
    hf_task.ocr("m/x", "i.png", "OCR:", out, read=lambda model, image, prompt: "read it")
    assert out.read_text(encoding="utf-8") == "read it"


def test_remote_code_is_refused_and_classed_as_needing_its_own_runner(tmp_path, capsys):
    from harness import hf_task

    def needs_code(model, image, prompt):
        raise ValueError("The repository m/x contains custom code which must be executed "
                         "to correctly load the model. Please pass trust_remote_code=True")
    rc = hf_task.main(["ocr", "--model", "m/x", "--image", "i.png", "--out",
                       str(tmp_path / "o.txt")], read=needs_code)
    err = capsys.readouterr().err
    assert rc != 0 and "trust_remote_code" in err
    assert reasons.classify(err, candidate="hf-ocr:m/x") == reasons.LOAD_FAILED_LAYOUT


def test_a_package_missing_from_the_venv_is_the_harness_not_the_model():
    """Measured: a venv without sentencepiece failed trocr on every case. #562."""
    msg = ("exit 1: You need to have sentencepiece or tiktoken installed to convert "
           "a slow tokenizer to a fast one.")
    assert reasons.classify(msg, candidate="hf-ocr:m/x") == reasons.HARNESS_ERROR


def test_an_unknown_architecture_is_a_runtime_gap_a_newer_transformers_may_close():
    msg = "ValueError: The checkpoint you are trying to load has model type `hayai`"
    assert reasons.classify(msg, candidate="hf-ocr:m/x") == reasons.LOAD_FAILED_RUNTIME


# --- the store -------------------------------------------------------------

def test_the_os_reader_keeps_no_weights_and_keeps_no_lane_from_deletion():
    """osocr loads nothing from the hub, so it must not hold every ocr download hostage."""
    from harness import disk
    k = disk.keepers(gateway_files=[], typed={"ocr": "osocr:auto"}, adopted={})
    assert "ocr" not in k.lanes
    assert not [p for p in k.problems if "osocr" in p]


def test_a_laneless_ocr_row_is_relaned_and_a_laned_row_is_not(tmp_path, monkeypatch):
    from harness import memory_store as ms
    from harness.memory_store.migrations import retractions
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    conn = ms.connect(tmp_path / "d.db")
    conn.execute("INSERT INTO proposals (name, lane, hf_task, card_tags, first_seen, last_seen) "
                 "VALUES ('a/ocr', '', 'image-text-to-text', ?, 0, 0)", (json.dumps(["ocr"]),))
    conn.execute("INSERT INTO proposals (name, lane, hf_task, card_tags, first_seen, last_seen) "
                 "VALUES ('b/vl', 'code', 'image-text-to-text', ?, 0, 0)", (json.dumps(["ocr"]),))
    retractions._relane_the_laneless_from_lineage(conn)
    got = dict(conn.execute("SELECT name, lane FROM proposals").fetchall())
    assert got == {"a/ocr": "ocr", "b/vl": "code"}
    assert ms.SCHEMA_VERSION >= 53


def test_a_recurring_ocr_model_is_no_longer_in_lanes_wanted():
    rows = [{"name": "PaddlePaddle/PaddleOCR-VL-1.6", "lane": "ocr", "times": 5},
            {"name": "a/translator", "lane": "", "times": 5, "hf_task": "translation"}]
    assert [r["name"] for r in rank.wanted(rows)] == ["a/translator"]
