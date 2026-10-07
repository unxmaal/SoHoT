"""The pii lane: mark the personal data in a sentence, scored on token F1. #564."""
import dataclasses
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals import run  # noqa: E402
from evals.core import Case, load_cases, score, summarize  # noqa: E402
from harness import discover, engines, inspect as ins, lanes, screen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECURRING = ("openai/privacy-filter", "LH-Tech-AI/Shield-82M", "mistralai/Shieldstral-1.0-3B")


def _load():
    try:
        return load_cases(ROOT / "evals" / "cases" / "pii")
    except ValueError:
        return []


CASES = _load()


def _gold_spans(c):
    return [[s, e] for s, e in c.params["spans"]]


# --- the lane --------------------------------------------------------------

def test_pii_is_wanted_after_retrieval():
    assert lanes.WANTED.index("pii") == lanes.WANTED.index("retrieval") + 1
    assert lanes.WANTED[-1] == "pii"


# --- routing ---------------------------------------------------------------

@pytest.mark.parametrize("repo", ["openai/privacy-filter", "LH-Tech-AI/Shield-82M"])
def test_each_token_classifying_privacy_filter_routes_to_pii(repo):
    import fakes
    assert ins.lane_and_source(fakes.card(repo)) == ("pii", "tag")


@pytest.mark.parametrize("task,tags,lane", [
    ("token-classification", ["pii"], "pii"),
    ("token-classification", ["anonymization"], "pii"),
    # A general named-entity tagger is not a privacy filter.
    ("token-classification", ["ner"], ""),
    ("token-classification", [], ""),
    # A classifier tagged pii decides; a text model tagged privacy writes code.
    ("text-classification", ["pii"], "decide"),
    ("text-generation", ["privacy"], "code"),
])
def test_pii_routing_steals_nothing_from_other_lanes(task, tags, lane):
    assert ins.lane_for({"pipeline_tag": task, "tags": tags}) == lane


def test_recorded_negative_controls():
    import fakes
    assert ins.lane_for(fakes.card("dslim/bert-base-NER")) == ""
    # A generative guard with no task and no pii tag keeps the code lane its lineage gives it (#557).
    assert ins.lane_for(fakes.card("mistralai/Shieldstral-1.0-3B")) == "code"


@pytest.mark.parametrize("repo", RECURRING)
def test_each_recurring_privacy_model_is_reachable_by_a_pii_query(repo):
    queries = [q.lower() for q in discover.lane_queries("pii")]
    assert any(q in repo.lower() for q in queries), queries


# --- the cases -------------------------------------------------------------

def test_the_lane_has_labelled_sentences_with_and_without_personal_data():
    assert len(CASES) >= 12
    with_pii = [c for c in CASES if c.assertions["pii"]]
    without = [c for c in CASES if not c.assertions["pii"]]
    assert len(with_pii) >= 8 and len(without) >= 3


def test_each_labelled_string_is_located_once_in_its_sentence():
    for c in CASES:
        spans = _gold_spans(c)
        assert [c.prompt[s:e] for s, e in spans] == c.assertions["pii"]


def test_a_label_that_is_not_in_the_sentence_is_refused(tmp_path):
    (tmp_path / "c.yaml").write_text("id: c\nmodality: pii\nprompt: Call Ann now\n"
                                     "assert: {pii: [Bob]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not in the sentence"):
        load_cases(tmp_path)


def test_a_label_that_occurs_twice_is_refused(tmp_path):
    (tmp_path / "c.yaml").write_text("id: c\nmodality: pii\nprompt: Ann met Ann\n"
                                     "assert: {pii: [Ann]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="more than once"):
        load_cases(tmp_path)


# --- the metric and its negative control -----------------------------------

def _rows(spans_for):
    rows = []
    for c in CASES:
        r = score(c, json.dumps({"spans": spans_for(c)}))
        r.candidate = "stub"
        rows.append(r)
    return summarize(rows)["stub"]


def test_token_f1_on_a_known_sentence():
    from harness.checks import pii
    text = "Mail Ann Lee at ann@example.com now"
    gold = [[5, 12], [16, 31]]
    assert pii.counts(text, gold, gold) == (5, 0, 0)
    assert pii.counts(text, gold, [[5, 8]]) == (1, 0, 4)
    assert pii.counts(text, gold, [[0, len(text)]]) == (5, 3, 0)


def test_negative_control_marking_nothing_or_everything_scores_clearly_worse():
    """Gauntlet: a metric quoted without a negative control. Two wrong stubs, one right one."""
    right = _rows(_gold_spans)
    nothing = _rows(lambda c: [])
    everything = _rows(lambda c: [[0, len(c.prompt)]])
    assert right["metrics"]["pii_f1"] == 1.0 and right["passed"] == len(CASES)
    assert nothing["metrics"].get("pii_f1", 0.0) == 0.0
    assert everything["metrics"]["pii_f1"] < 0.6
    no_pii = sum(1 for c in CASES if not c.assertions["pii"])
    assert nothing["passed"] == no_pii and everything["passed"] == 0


def test_label_names_do_not_matter_only_which_tokens_are_marked():
    c = next(c for c in CASES if c.id == "pii-email-name")
    spans = [[s, e, "private_person"] for s, e in _gold_spans(c)]
    r = score(c, json.dumps({"spans": spans}))
    assert r.passed and r.metrics["pii_tp"] > 0 and r.metrics["pii_pred"] == r.metrics["pii_tp"]


def test_an_unparseable_answer_fails():
    r = score(CASES[0], "nope")
    assert not r.passed and "spans" in r.detail


def test_the_pattern_baseline_is_between_the_controls():
    """Regexes catch emails, numbers and keys and miss every name."""
    from harness import pattern_pii
    got = _rows(lambda c: pattern_pii.find(c.prompt))
    assert 0.3 < got["metrics"]["pii_f1"] < 0.9


# --- engines and the runner ------------------------------------------------

def test_the_pattern_baseline_is_a_weightless_process_engine(tmp_path):
    from harness import disk
    e = engines.resolve("pii-regex")
    assert e.modality == "pii" and e.output_suffix == ".json"
    assert "harness.pattern_pii" in e.argv("text", tmp_path / "o.json", {})
    with pytest.raises(ValueError, match="takes no model"):
        engines.resolve("pii-regex:org/m")
    assert "pii-regex" in disk.WEIGHTLESS


def test_a_transformers_token_classifier_is_a_process_engine(tmp_path):
    e = engines.resolve("hf-pii:openai/privacy-filter,device=cpu")
    argv = e.argv("Call Ann", tmp_path / "o.json", {})
    assert argv[1] == "pii" and argv[argv.index("--text") + 1] == "Call Ann"
    assert argv[argv.index("--model") + 1] == "openai/privacy-filter"
    with pytest.raises(ValueError, match="needs a model"):
        engines.resolve("hf-pii:")


def test_the_lane_spells_a_discovered_model_for_the_token_classifier():
    assert screen.candidate_for("pii", "org/m") == "hf-pii:org/m"
    assert screen.candidate_for("pii", "pii-regex") == "pii-regex"


def test_a_privacy_model_this_harness_cannot_load_is_a_runner_wanted():
    import fakes
    card = fakes.card("mistralai/Shieldstral-1.0-3B")
    row = {"name": "m", "lane": "pii", "hf_task": card["pipeline_tag"] or "",
           "library": card["library_name"], "card_tags": card["tags"]}
    assert "vllm" in screen.runner_gap("pii", "mistralai/Shieldstral-1.0-3B", card=row)
    ok = fakes.card("openai/privacy-filter")
    row = {"name": "o", "hf_task": ok["pipeline_tag"], "library": ok["library_name"],
           "card_tags": ok["tags"]}
    assert screen.runner_gap("pii", "openai/privacy-filter", card=row) == ""


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/engines.py:HF_LIBRARIES")
@pytest.mark.parametrize("spec", ["hf-ocr:PaddlePaddle/PaddleOCR-VL-1.6", "bm25",
                                  "mflux:flux2-klein-4b", "pii-regex"])
def test_an_engine_the_library_table_does_not_name_refuses_no_library(spec):
    """An unlisted engine asks nothing of the card's library: PaddleOCR-VL's card says
    PaddleOCR and transformers loads it natively."""
    assert engines.card_gap(spec, {"library": "PaddleOCR", "hf_task": "image-text-to-text"}) == ""
    assert set(engines.HF_LIBRARIES) <= engines.names()


def test_run_selects_only_pii_cases_for_a_pii_engine():
    mixed = [Case(id="p", modality="pii", prompt="p"), Case(id="c", modality="code", prompt="p")]
    assert [c.id for c in run.cases_for("pii-regex", mixed)] == ["p"]
    assert "p" not in [c.id for c in run.cases_for("q3-4b", mixed)]


def test_the_typed_default_is_the_pattern_baseline():
    from harness import cli, verify, winners
    assert winners.typed()["pii"] == cli.DEFAULT_PII_ENGINE == "pii-regex"
    assert winners.FAMILIES["pii"] == "engine"
    assert verify.COST_S["pii"] > 0


def test_a_pattern_run_through_the_process_runner_is_scored(tmp_path):
    from evals.runners.process import ProcessRunner
    case = next(c for c in CASES if c.id == "pii-api-key")
    r = ProcessRunner(engines.resolve("pii-regex"), tmp_path).run(case)
    assert r.passed, r.detail


# --- the script that runs in the transformers venv -------------------------

@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:HF_TASK_BIN")
def test_the_pii_argv_is_what_hf_task_accepts(monkeypatch, tmp_path):
    from harness import hf_task
    monkeypatch.delenv("HF_TASK_BIN", raising=False)
    out = tmp_path / "o.json"
    argv = engines.resolve("hf-pii:m/p").argv("Call Ann", out, {})
    assert Path(argv[0]) == ROOT / "scripts" / "hf-task.sh"

    def tag(model, text):
        assert (model, text) == ("m/p", "Call Ann")
        return [{"start": 5, "end": 8, "entity_group": "private_person"}]
    assert hf_task.main(argv[1:], tag=tag) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"spans": [[5, 8, "private_person"]]}


def test_a_remote_code_privacy_model_is_refused(tmp_path, capsys):
    from harness import hf_task, reasons

    def needs_code(model, text):
        raise ValueError("Please pass the argument `trust_remote_code=True`")
    rc = hf_task.main(["pii", "--model", "m/x", "--text", "t", "--out",
                       str(tmp_path / "o.json")], tag=needs_code)
    assert rc == hf_task.NEEDS_OWN_RUNNER
    assert reasons.classify(capsys.readouterr().err, candidate="hf-pii:m/x") \
        == reasons.LOAD_FAILED_LAYOUT


# --- the store -------------------------------------------------------------

def test_a_laneless_privacy_filter_row_is_relaned(tmp_path):
    from harness import memory_store as ms
    from harness.memory_store.migrations import retractions
    conn = ms.connect(tmp_path / "d.db")
    conn.execute("INSERT INTO proposals (name, lane, hf_task, card_tags, first_seen, last_seen)"
                 " VALUES ('a/pf', '', 'token-classification', ?, 0, 0)",
                 (json.dumps(["pii", "roberta"]),))
    conn.execute("INSERT INTO proposals (name, lane, hf_task, card_tags, first_seen, last_seen)"
                 " VALUES ('b/ner', '', 'token-classification', ?, 0, 0)",
                 (json.dumps(["ner"]),))
    retractions._relane_the_laneless_from_lineage(conn)
    got = dict(conn.execute("SELECT name, lane FROM proposals").fetchall())
    assert got == {"a/pf": "pii", "b/ner": ""}
    assert ms.SCHEMA_VERSION >= 55
