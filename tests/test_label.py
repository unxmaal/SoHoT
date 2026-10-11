"""Batch decide and label scoring: local model labels, Claude checks a sample. #683."""
from __future__ import annotations

import json
import threading

import pytest

from harness import cli, label


SCHEMA = {"q1": {"type": "boolean", "description": "true if stated"},
          "q2": {"type": "boolean", "description": "true if stated"}}


def _items(n):
    return [{"id": f"check-squad2-{i}", "question": "Which?", "context": f"c{i}",
             "schema": SCHEMA} for i in range(n)]


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _read_jsonl(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def fake_decide(question, schema, context=""):
    return {"answers": {f: True for f in schema},
            "probabilities": {f: {True: 0.8, False: 0.2} for f in schema},
            "lane": "decide", "model": "fake"}


def test_batch_writes_one_line_per_item_with_answers_and_probs(tmp_path):
    out = tmp_path / "out.jsonl"
    got = label.run_batch(_items(3), out, decide=fake_decide, concurrency=2)
    rows = {r["id"]: r for r in _read_jsonl(out)}
    assert set(rows) == {f"check-squad2-{i}" for i in range(3)}
    assert rows["check-squad2-0"]["answers"] == {"q1": True, "q2": True}
    assert rows["check-squad2-0"]["probs"]["q1"] == {"true": 0.8, "false": 0.2}
    assert rows["check-squad2-0"]["error"] is None
    assert got == {"done": 3, "skipped": 0, "errors": 0, "missing": []}


def test_a_failed_item_gets_an_error_line_not_silence(tmp_path):
    def flaky(question, schema, context=""):
        if context == "c1":
            raise ValueError("no usable answer for q1")
        return fake_decide(question, schema, context)
    out = tmp_path / "out.jsonl"
    got = label.run_batch(_items(3), out, decide=flaky)
    rows = {r["id"]: r for r in _read_jsonl(out)}
    assert len(rows) == 3
    assert rows["check-squad2-1"]["error"] == "no usable answer for q1"
    assert rows["check-squad2-1"]["answers"] == {}
    assert got["errors"] == 1


def test_a_malformed_input_item_gets_an_error_line(tmp_path):
    out = tmp_path / "out.jsonl"
    items = [{"id": "a", "question": "q", "context": "", "schema": "not a schema"},
             {"question": "no id", "schema": SCHEMA}]
    label.run_batch(items, out, decide=fake_decide)
    rows = _read_jsonl(out)
    assert len(rows) == 2
    assert all(r["error"] for r in rows)
    assert rows[1]["id"] == "line:2"


def test_resume_skips_ids_already_answered_and_retries_errors(tmp_path):
    out = tmp_path / "out.jsonl"
    _write_jsonl(out, [
        {"id": "check-squad2-0", "answers": {"q1": False, "q2": False},
         "probs": {}, "error": None},
        {"id": "check-squad2-1", "answers": {}, "probs": {}, "error": "boom"}])
    asked = []

    def spy(question, schema, context=""):
        asked.append(context)
        return fake_decide(question, schema, context)
    got = label.run_batch(_items(3), out, decide=spy)
    assert sorted(asked) == ["c1", "c2"]
    assert got["skipped"] == 1
    final = label.latest(_read_jsonl(out))
    assert final["check-squad2-0"]["answers"] == {"q1": False, "q2": False}
    assert final["check-squad2-1"]["error"] is None


def test_the_batch_runs_concurrently(tmp_path):
    seen, lock, gate = [], threading.Lock(), threading.Barrier(3, timeout=5)

    def slow(question, schema, context=""):
        gate.wait()
        with lock:
            seen.append(context)
        return fake_decide(question, schema, context)
    label.run_batch(_items(3), tmp_path / "o.jsonl", decide=slow, concurrency=3)
    assert len(seen) == 3


def test_read_items_takes_jsonl_or_a_json_array(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.json"
    _write_jsonl(a, _items(2))
    b.write_text(json.dumps(_items(2)), encoding="utf-8")
    assert label.read_items(a) == label.read_items(b) == _items(2)


def test_a_bad_jsonl_line_becomes_an_item_that_errors(tmp_path):
    a = tmp_path / "a.jsonl"
    a.write_text(json.dumps(_items(1)[0]) + "\n{not json\n", encoding="utf-8")
    out = tmp_path / "o.jsonl"
    label.run_batch(label.read_items(a), out, decide=fake_decide)
    rows = _read_jsonl(out)
    assert len(rows) == 2 and rows[1]["error"]


def test_decide_batch_cli_uses_the_delegate_decide_path(tmp_path, monkeypatch):
    from harness import delegate
    calls = []

    def fake(question, schema, context="", timeout=None):
        calls.append(question)
        return fake_decide(question, schema, context)
    monkeypatch.setattr(delegate, "decide", fake)
    inp, out = tmp_path / "in.jsonl", tmp_path / "out.jsonl"
    _write_jsonl(inp, _items(2))
    rc = cli.main(["decide", "--batch", str(inp), "--out", str(out),
                   "--concurrency", "2"])
    assert rc == 0
    assert len(calls) == 2 and len(_read_jsonl(out)) == 2


def test_decide_batch_cli_needs_out(tmp_path):
    inp = tmp_path / "in.jsonl"
    _write_jsonl(inp, _items(1))
    assert cli.main(["decide", "--batch", str(inp)]) != 0


def test_decide_without_batch_still_needs_a_prompt_and_schema():
    assert cli.main(["decide"]) != 0


def _label(id_, answers, conf):
    return {"id": id_, "answers": answers, "error": None,
            "probs": {f: {str(v).lower(): conf[f], "other": 1 - conf[f]}
                      for f, v in answers.items()}}


LABELS = [
    _label("check-squad2-a", {"q1": True, "q2": False}, {"q1": 0.99, "q2": 0.6}),
    _label("check-squad2-b", {"q1": True, "q2": True}, {"q1": 0.95, "q2": 0.7}),
    _label("guard-browsesafe-1", {"page1": False}, {"page1": 0.97}),
    {"id": "guard-browsesafe-2", "answers": {}, "probs": {}, "error": "boom"},
]
GOLD = {"check-squad2-a": {"q1": True, "q2": True},
        "check-squad2-b": {"q1": True, "q2": True},
        "guard-browsesafe-1": {"page1": True},
        "guard-browsesafe-2": {"page1": True}}
CHECKS = [{"id": "check-squad2-a", "answers": {"q2": True}},
          {"id": "check-squad2-b", "answers": {"q2": False}}]


def test_family_is_the_id_without_its_last_part():
    assert label.family("policy-civil-comments-10275") == "policy-civil-comments"
    assert label.family("check-squad2-56de16") == "check-squad2"


def test_score_counts_coverage_and_errors():
    s = label.score(LABELS, CHECKS, GOLD)
    assert s["items"] == 4 and s["labelled"] == 3 and s["errors"] == 1


def test_score_accuracy_per_field_and_family():
    s = label.score(LABELS, CHECKS, GOLD)
    assert s["by_field"]["q1"] == {"n": 2, "right": 2, "acc": 1.0}
    assert s["by_field"]["q2"] == {"n": 2, "right": 1, "acc": 0.5}
    assert s["by_family"]["check-squad2"]["acc"] == 0.75
    assert s["by_family"]["guard-browsesafe"]["acc"] == 0.0
    assert s["local"] == {"n": 5, "right": 3, "acc": 0.6}


def test_score_accuracy_by_confidence_band():
    bands = {b["band"]: b for b in label.score(LABELS, CHECKS, GOLD)["by_band"]}
    assert bands["0.95-0.99"]["n"] == 2
    assert bands["0.99-1.00"]["right"] == 1
    assert bands["0.50-0.70"] == {"band": "0.50-0.70", "n": 1, "right": 0, "acc": 0.0}


def test_score_agreement_and_who_was_right():
    a = label.score(LABELS, CHECKS, GOLD)["agreement"]
    assert a["checked"] == 2 and a["agree"] == 0
    assert a["disagree"] == 2
    assert a["claude_right"] == 1 and a["local_right"] == 1 and a["neither"] == 0


def test_score_final_takes_claude_on_checked_fields():
    s = label.score(LABELS, CHECKS, GOLD)
    assert s["final"] == {"n": 5, "right": 3, "acc": 0.6}
    assert s["claude"] == {"n": 2, "right": 1, "acc": 0.5}


def test_threshold_is_the_lowest_confidence_whose_tail_reaches_target():
    rows = [(0.5, False), (0.6, True), (0.7, False), (0.8, True), (0.9, True), (0.99, True)]
    assert label.threshold(rows, 0.95) == 0.8
    assert label.threshold(rows, 0.5) == 0.5
    assert label.threshold([(0.9, False)], 0.95) is None
    assert label.threshold([], 0.95) is None


def test_score_suggests_a_threshold_per_field():
    t = label.score(LABELS, CHECKS, GOLD, target=0.95)["thresholds"]
    assert t["q1"] == 0.95
    assert t["q2"] == 0.7
    assert t["page1"] is None


def test_without_gold_claude_is_the_reference_on_checked_fields():
    s = label.score(LABELS, CHECKS, None)
    assert s["reference"] == "claude"
    assert s["local"] == {"n": 2, "right": 0, "acc": 0.0}
    assert "claude_right" not in s["agreement"]


def test_render_names_every_section():
    text = label.render(label.score(LABELS, CHECKS, GOLD))
    for word in ("coverage", "by field", "by family", "by confidence",
                 "agreement", "threshold"):
        assert word in text


def test_label_score_cli_reads_files(tmp_path, capsys):
    lab, chk, gold = tmp_path / "l.jsonl", tmp_path / "c.jsonl", tmp_path / "g.json"
    _write_jsonl(lab, LABELS)
    _write_jsonl(chk, CHECKS)
    gold.write_text(json.dumps(GOLD), encoding="utf-8")
    assert cli.main(["label-score", "--labels", str(lab), "--checks", str(chk),
                     "--gold", str(gold), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)["body"]
    assert body["agreement"]["claude_right"] == 1


def test_label_score_cli_runs_without_checks_or_gold(tmp_path, capsys):
    lab = tmp_path / "l.jsonl"
    _write_jsonl(lab, LABELS)
    assert cli.main(["label-score", "--labels", str(lab)]) == 0
    assert "coverage" in capsys.readouterr().out


@pytest.mark.parametrize("value,want", [(True, "true"), (False, "false"), ("x", "x")])
def test_choice_keys_are_strings(value, want):
    assert label.key(value) == want


def test_label_score_cli_takes_gold_as_jsonl(tmp_path, capsys):
    lab, gold = tmp_path / "l.jsonl", tmp_path / "g.jsonl"
    _write_jsonl(lab, LABELS)
    _write_jsonl(gold, [{"id": i, "answers": a} for i, a in GOLD.items()])
    assert cli.main(["label-score", "--labels", str(lab), "--gold", str(gold),
                     "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["body"]["local"]["n"] == 5


def test_batch_reports_ids_still_without_an_answer(tmp_path):
    def flaky(question, schema, context=""):
        if context == "c1":
            raise ValueError("boom")
        return fake_decide(question, schema, context)
    got = label.run_batch(_items(3), tmp_path / "o.jsonl", decide=flaky)
    assert got["missing"] == ["check-squad2-1"]


def _item(id_, fields):
    return {"id": id_, "question": "Which?", "context": "ctx",
            "schema": {f: {"type": "boolean", "description": f"is {f}"} for f in fields}}


SEL_ITEMS = [_item("a-1", ["q1", "q2"]), _item("a-2", ["q1", "q2"]),
             _item("a-3", ["q1"]), _item("a-4", ["q1"])]
SEL_LABELS = [_label("a-1", {"q1": True, "q2": True}, {"q1": 0.95, "q2": 0.6}),
              _label("a-2", {"q1": True, "q2": True}, {"q1": 0.99, "q2": 0.99}),
              {"id": "a-3", "answers": {}, "probs": {}, "error": "boom"},
              _label("a-4", {"q1": False}, {"q1": 0.8})]


def test_select_sends_only_fields_below_the_threshold_without_answers():
    todo = label.select(SEL_ITEMS, SEL_LABELS, threshold=0.9)
    assert [(t["id"], sorted(t["schema"])) for t in todo] == [("a-1", ["q2"]), ("a-4", ["q1"])]
    assert "answers" not in todo[0] and "probs" not in todo[0]
    assert todo[0]["schema"]["q2"]["description"] == "is q2"


def test_select_takes_a_threshold_per_field():
    todo = label.select(SEL_ITEMS, SEL_LABELS, threshold=0.9, thresholds={"q2": 0.5})
    assert [(t["id"], sorted(t["schema"])) for t in todo] == [("a-4", ["q1"])]


def test_select_samples_every_nth_item_whole():
    todo = label.select(SEL_ITEMS, SEL_LABELS, threshold=0.0, every=2)
    assert [(t["id"], sorted(t["schema"])) for t in todo] == [("a-1", ["q1", "q2"])]


def test_label_select_cli_writes_the_todo(tmp_path, capsys):
    inp, lab, out = tmp_path / "i.jsonl", tmp_path / "l.jsonl", tmp_path / "t.jsonl"
    _write_jsonl(inp, SEL_ITEMS)
    _write_jsonl(lab, SEL_LABELS)
    assert cli.main(["label-select", "--items", str(inp), "--labels", str(lab),
                     "--out", str(out), "--thresholds", '{"q2": 0.5}', "--json"]) == 0
    body = json.loads(capsys.readouterr().out)["body"]
    assert body == {"items": 1, "fields": 1, "out": str(out)}
    assert _read_jsonl(out)[0]["id"] == "a-4"
