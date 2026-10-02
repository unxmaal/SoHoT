"""Rubric evaluation by a local model, scored against a person's labels. #286."""
import json
import random
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import rubric_eval as rv  # noqa: E402

RUBRIC = {
    "name": "durable-fact", "version": 1,
    "instructions": "Does the message state a durable technical fact?",
    "label": "verdict",
    "schema": {"type": "object", "additionalProperties": False,
               "required": ["verdict", "why"],
               "properties": {"verdict": {"enum": ["fact", "no-fact"]},
                              "why": {"type": "string"}}},
}
ITEMS = [{"id": "a", "text": "Set J6 to 2-3 for a serial console."},
         {"id": "b", "text": "lol same"},
         {"id": "c", "text": "The Octane PSU is 600 W."}]


@pytest.fixture
def evalset(tmp_path):
    (tmp_path / "rubric.yaml").write_text(yaml.safe_dump(RUBRIC), encoding="utf-8")
    (tmp_path / "items.jsonl").write_text(
        "".join(json.dumps(i) + "\n" for i in ITEMS), encoding="utf-8")
    return tmp_path


class FakePost:
    """Answers per item text; records what was sent."""

    def __init__(self, answers):
        self.answers, self.sent = answers, []

    def __call__(self, url, json=None, timeout=None, headers=None):
        self.sent.append(json)
        text = json["messages"][-1]["content"]
        reply = self.answers[text]

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):
                return {"choices": [{"message": {"content": reply}}]}
        return R()


# --- the rubric ----------------------------------------------------------

def test_a_rubric_names_its_label_values_from_the_schema(evalset):
    r = rv.load_set(evalset).rubric
    assert r.labels == ("fact", "no-fact")


def test_a_rubric_whose_label_field_has_no_enum_is_refused(tmp_path):
    bad = dict(RUBRIC, schema={"type": "object", "required": ["verdict"],
                               "properties": {"verdict": {"type": "string"}}})
    (tmp_path / "rubric.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    (tmp_path / "items.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="enum"):
        rv.load_set(tmp_path)


def test_editing_the_instructions_changes_the_stamp(evalset):
    """Gauntlet #9: identity by content. A version is a name."""
    before = rv.load_set(evalset).rubric.stamp
    edited = dict(RUBRIC, instructions=RUBRIC["instructions"] + " Be strict.")
    (evalset / "rubric.yaml").write_text(yaml.safe_dump(edited), encoding="utf-8")
    assert rv.load_set(evalset).rubric.stamp != before


def test_duplicate_item_ids_are_refused(tmp_path):
    (tmp_path / "rubric.yaml").write_text(yaml.safe_dump(RUBRIC), encoding="utf-8")
    (tmp_path / "items.jsonl").write_text(
        json.dumps(ITEMS[0]) + "\n" + json.dumps(ITEMS[0]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        rv.load_set(tmp_path)


# --- labels ----------------------------------------------------------------

def test_labels_append_and_never_rewrite(evalset):
    rv.record_label(evalset, "a", "fact")
    rv.record_label(evalset, "a", "no-fact", repeat=True)
    assert rv.labels(evalset)["a"] == ["fact", "no-fact"]


def test_a_label_outside_the_rubric_is_refused(evalset):
    with pytest.raises(ValueError):
        rv.record_label(evalset, "a", "maybe")


def test_an_unknown_item_is_refused(evalset):
    with pytest.raises(KeyError):
        rv.record_label(evalset, "zzz", "fact")


def test_cant_tell_is_recorded_but_is_never_gold(evalset):
    rv.record_label(evalset, "a", rv.CANT_TELL)
    assert rv.labels(evalset)["a"] == [rv.CANT_TELL]
    assert "a" not in rv.gold(evalset)


def test_gold_is_the_majority_and_a_tie_is_not_gold(evalset):
    for lab in ("fact", "fact", "no-fact"):
        rv.record_label(evalset, "a", lab)
    rv.record_label(evalset, "b", "fact")
    rv.record_label(evalset, "b", "no-fact")
    assert rv.gold(evalset) == {"a": "fact"}


def test_self_agreement_counts_repeats_against_the_first_answer(evalset):
    rv.record_label(evalset, "a", "fact")
    rv.record_label(evalset, "a", "fact", repeat=True)
    rv.record_label(evalset, "b", "no-fact")
    rv.record_label(evalset, "b", "fact", repeat=True)
    rv.record_label(evalset, "c", "fact")
    assert rv.self_agreement(evalset) == (1, 2)


def test_next_item_serves_the_unlabelled_before_anything_else(evalset):
    rv.record_label(evalset, "a", "fact")
    item, repeat = rv.next_item(evalset, random.Random(0), repeat_rate=0.0)
    assert item["id"] in ("b", "c") and not repeat


def test_next_item_repeats_a_labelled_item_at_the_repeat_rate(evalset):
    rv.record_label(evalset, "a", "fact")
    item, repeat = rv.next_item(evalset, random.Random(0), repeat_rate=1.0)
    assert item["id"] == "a" and repeat


def test_next_item_is_none_when_everything_is_labelled(evalset):
    for i in ITEMS:
        rv.record_label(evalset, i["id"], "fact")
    assert rv.next_item(evalset, random.Random(0), repeat_rate=0.0) is None


# --- the request -----------------------------------------------------------

def test_the_request_enforces_the_schema_and_puts_the_rubric_first(evalset):
    r = rv.load_set(evalset).rubric
    body = rv.request(r, "hello", "eval-4b")
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["schema"] == RUBRIC["schema"]
    assert fmt["json_schema"]["strict"] is True
    assert body["messages"][0] == {"role": "system", "content": r.instructions}
    assert body["messages"][-1]["content"] == "hello"
    assert body["temperature"] == 0


def test_a_valid_reply_yields_its_label(evalset):
    r = rv.load_set(evalset).rubric
    post = FakePost({"x": '{"verdict": "fact", "why": "a jumper"}'})
    got = rv.evaluate(r, "x", "m", "http://gw", post=post)
    assert got.ok and got.label == "fact"


def test_a_reply_that_breaks_the_schema_is_invalid_not_a_label(evalset):
    """The control for the enforcement: the server is not trusted to have
    applied it, so the client checks."""
    r = rv.load_set(evalset).rubric
    post = FakePost({"x": '{"verdict": "hardware tip", "why": ""}'})
    got = rv.evaluate(r, "x", "m", "http://gw", post=post)
    assert not got.ok and got.label is None and got.error


def test_prose_is_invalid(evalset):
    r = rv.load_set(evalset).rubric
    got = rv.evaluate(r, "x", "m", "http://gw", post=FakePost({"x": "It is a fact."}))
    assert not got.ok


# --- the run ---------------------------------------------------------------

def _label_all(evalset):
    rv.record_label(evalset, "a", "fact")
    rv.record_label(evalset, "a", "fact", repeat=True)
    rv.record_label(evalset, "b", "no-fact")
    rv.record_label(evalset, "c", "fact")


def test_a_run_scores_agreement_only_over_gold_items(evalset):
    _label_all(evalset)
    post = FakePost({
        ITEMS[0]["text"]: '{"verdict": "fact", "why": ""}',
        ITEMS[1]["text"]: '{"verdict": "fact", "why": ""}',
        ITEMS[2]["text"]: "not json"})
    report = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)
    row = report["candidates"]["m"]
    assert (row["n"], row["valid"], row["agree"]) == (3, 2, 1)


def test_a_run_reports_its_floor_and_ceiling(evalset):
    """Gauntlet #1. Agreement means nothing without the majority-class floor
    and the labeller's own repeat agreement as ceiling."""
    _label_all(evalset)
    post = FakePost({i["text"]: '{"verdict": "fact", "why": ""}' for i in ITEMS})
    report = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)
    assert report["floor"] == pytest.approx(2 / 3)
    assert report["ceiling"] == (1, 1)
    assert report["candidates"]["m"]["agreement"] == pytest.approx(2 / 3)
    assert not report["candidates"]["m"]["beats_floor"]


def test_a_candidate_above_the_floor_says_so(evalset):
    _label_all(evalset)
    post = FakePost({ITEMS[0]["text"]: '{"verdict": "fact", "why": ""}',
                     ITEMS[1]["text"]: '{"verdict": "no-fact", "why": ""}',
                     ITEMS[2]["text"]: '{"verdict": "fact", "why": ""}'})
    report = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)
    assert report["candidates"]["m"]["beats_floor"]


def test_a_run_with_no_gold_refuses(evalset):
    with pytest.raises(ValueError, match="label"):
        rv.run(rv.load_set(evalset), ["m"], "http://gw", post=FakePost({}))


def test_the_receipt_carries_what_makes_two_runs_comparable(evalset):
    _label_all(evalset)
    post = FakePost({i["text"]: '{"verdict": "fact", "why": ""}' for i in ITEMS})
    report = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)
    assert report["rubric"] == rv.load_set(evalset).rubric.stamp
    assert report["labels_digest"] and report["temperature"] == 0


def test_the_receipt_keeps_every_answer_not_just_the_totals(evalset):
    """RULE #316: an aggregate cannot be re-read; the raw replies can."""
    _label_all(evalset)
    post = FakePost({i["text"]: '{"verdict": "fact", "why": "w"}' for i in ITEMS})
    report = rv.run(rv.load_set(evalset), ["m"], "http://gw", post=post)
    rows = {r["id"]: r for r in report["rows"]}
    assert set(rows) == {"a", "b", "c"}
    assert rows["b"]["gold"] == "no-fact" and rows["b"]["label"] == "fact"
    assert rows["b"]["raw"] == '{"verdict": "fact", "why": "w"}'


def test_every_label_records_the_interface_that_collected_it(evalset):
    """RULE #309: a UI change partitions labels into eras that must not mix."""
    rv.record_label(evalset, "a", "fact")
    row = json.loads((evalset / "labels.jsonl").read_text(encoding="utf-8"))
    assert row["interface"] == rv.INTERFACE
