"""Laya zero-shot on the decide cases: field mapping, grading by decide.check, the stored arm and the shuffle control. #970."""
import json
from pathlib import Path

from evals import core
from evals.analysis import laya_decide as L
from harness.checks import decide

CASES = Path(core.__file__).resolve().parent / "cases" / "decide"
PICK = ("route-massive", "policy-civil-comments", "rate-helpsteer2", "check-squad2")


def _cases():
    every = core.load_cases(CASES)
    return [next(c for c in every if c.id.startswith(p)) for p in PICK]


class FirstOption:
    """Answers each choice with its first listed option at 0.7 and every noul true at 0.8, so order matters."""

    def __init__(self):
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append(state)
        out = {}
        for name, q in questions.items():
            if q["type"] == "noul":
                out[name] = {"type": "noul", "noul": 0.8}
            else:
                keys = list(q["criteria"])
                rest = 0.3 / (len(keys) - 1)
                out[name] = {"type": "choice", "choice": keys[0],
                             "probabilities": {k: (0.7 if i == 0 else rest) for i, k in enumerate(keys)}}
        return {"answers": out, "usage": {"truncated": False, "truncated_questions": []}}


def _first_option_truth(case):
    schema, gold = case.params["schema"], case.assertions["answers"]
    return [decide.key(gold[n]) == ("true" if s["type"] == "boolean" else str(s["choices"][0]))
            for n, s in schema.items()]


def _fake_predictor(inp, dest):
    rows = [json.loads(line) for line in Path(inp).read_text(encoding="utf-8").splitlines()]
    dest.write_text("".join(json.dumps(r) + "\n" for r in L.predict(rows, FirstOption())), encoding="utf-8")


def test_a_boolean_field_is_a_noul_question_and_an_enum_a_choice_in_schema_order():
    schema = {"domain": {"type": "enum", "choices": ["alarm", "music"], "description": " Which domain? ",
                         "choice_descriptions": {"alarm": "setting alarms"}},
              "urgent": {"type": "boolean", "description": "Is it urgent?"}}
    q = L.questions("c", schema)
    assert q["urgent"] == {"type": "noul", "instructions": "Is it urgent?"}
    assert q["domain"] == {"type": "choice", "instructions": "Which domain?",
                           "criteria": {"alarm": "setting alarms", "music": ""}}


def test_a_seeded_shuffle_permutes_the_options_the_same_way_every_time():
    schema = {"f": {"type": "enum", "choices": [str(i) for i in range(12)], "description": "d"}}
    a, b = L.questions("c", schema, seed=970), L.questions("c", schema, seed=970)
    assert list(a["f"]["criteria"]) == list(b["f"]["criteria"])
    assert sorted(a["f"]["criteria"], key=int) == [str(i) for i in range(12)]
    assert list(a["f"]["criteria"]) != [str(i) for i in range(12)]


def test_the_state_is_the_question_and_its_material_without_the_lettered_reply_format():
    for case in _cases():
        s = L.state(case)
        assert "Answer every field below" not in s and "Reply with only a JSON" not in s
        assert s.startswith(case.prompt.split("\n\n")[0].strip()) and case.context.strip()[:40] in s


def test_a_noul_below_one_half_answers_false_and_keeps_its_distribution():
    schema = {"x": {"type": "boolean", "description": "d"}}
    got = L.artifact({"x": {"noul": 0.3}}, schema)
    assert got == {"answers": {"x": "false"}, "probabilities": {"x": {"true": 0.3, "false": 0.7}}}
    assert decide.check(got, schema, {"x": False}).ok


def test_the_warm_up_call_is_not_timed():
    ticks = iter([0.0, 2.0, 10.0, 10.5])
    agent = FirstOption()
    rows = [{"id": "a", "state": "s1", "questions": {}}, {"id": "b", "state": "s2", "questions": {}}]
    got = L.predict(rows, agent, clock=lambda: next(ticks))
    assert agent.calls == ["s1", "s1", "s2"] and [r["seconds"] for r in got] == [2.0, 0.5]


def test_grading_is_decide_check_on_every_field():
    cases = _cases()
    rows = [json.loads(json.dumps(r)) for r in L.predict(L.export(cases), FirstOption())]
    graded = L.grade(cases, rows)
    truth = [_first_option_truth(c) for c in cases]
    assert [r["decide_correct"] for r in graded] == [sum(t) for t in truth]
    assert [r["passed"] for r in graded] == [all(t) for t in truth]
    assert [[k for _, k in r["decisions"]] for r in graded] == [[int(x) for x in t] for t in truth]
    s = L.summarize(graded)
    assert s["fields"] == sum(len(t) for t in truth) and s["correct"] == sum(map(sum, truth))
    assert all(r["calibrated"] == 1.0 for r in graded) and s["brier"] is not None


def _copy_cases(tmp_path):
    d = tmp_path / "cases"
    d.mkdir()
    for case in _cases():
        (d / case.source.name).write_text(case.source.read_text(encoding="utf-8"), encoding="utf-8")
    return d


def _store(tmp_path, store_run, cases, digest, candidate="imajev-4b-Q8_0"):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    rows = [{"candidate": candidate, "case_id": c.id, "passed": i == 0, "seconds": 0.5,
             "metrics": {"decide_correct": 5 - i, "decide_fields": 5, "calibrated": 1.0,
                         "decide_brier_sum": 0.1 * i, "decisions": [[0.9, 1]] * (5 - i) + [[0.6, 0]] * i}}
            for i, c in enumerate(cases)]
    run_id = store_run("run-a", "decide", rows=rows, cases_digest=digest, conn=conn)
    conn.close()
    return tmp_path / "s.db", run_id


def test_the_stored_arm_is_read_on_the_same_case_ids_and_its_digest_is_checked(tmp_path, store_run):
    cases_dir = _copy_cases(tmp_path)
    cases = core.load_cases(cases_dir)
    digest = core.cases_digest(cases)[:16]
    db, run_id = _store(tmp_path, store_run, cases, digest)
    text = L.run(cases_dir, tmp_path / "out", str(db), run_id, _fake_predictor)
    assert f"cases_digest {digest}; stored run's {digest} (same case set)" in text
    row = next(line for line in text.splitlines() if line.startswith("| imajev-4b-Q8_0"))
    assert "| 14/20 0.700 [0.481, 0.855] | 1/4 [0.046, 0.699] | 0.030 | 0.250 | " in row
    assert "Laya, options shuffled" in text and "negative control (options shuffled" in text


def test_a_stored_run_over_another_case_set_is_said(tmp_path, store_run):
    cases_dir = _copy_cases(tmp_path)
    cases = core.load_cases(cases_dir)
    db, run_id = _store(tmp_path, store_run, cases, "0" * 16)
    text = L.run(cases_dir, tmp_path / "out", str(db), run_id, _fake_predictor, shuffle=False)
    assert "(DIFFERENT case set)" in text


def test_shuffling_options_changes_a_first_option_answerer_on_enum_fields_only(tmp_path):
    cases_dir = _copy_cases(tmp_path)
    text = L.run(cases_dir, tmp_path / "out", "", None, _fake_predictor)
    cases = core.load_cases(cases_dir)
    enums = sum(1 for c in cases for s in c.params["schema"].values() if s["type"] == "enum")
    changed, total = map(int, text.split("): ")[1].split(" enum verdicts")[0].split(" of "))
    assert total == enums and 0 < changed <= enums
    ordered = L.grade(cases, L._read(tmp_path / "out" / "ordered.pred.jsonl"))
    shuffled = L.grade(cases, L._read(tmp_path / "out" / "shuffled.pred.jsonl"))
    every = L.flips(ordered, shuffled)
    assert every["changed"] == changed and every["fields"] == sum(len(c.params["schema"]) for c in cases)
    assert L.flips(ordered, ordered, cases)["changed"] == 0


def test_predictions_already_on_disk_are_graded_again_without_rerunning_the_model(tmp_path):
    cases_dir = _copy_cases(tmp_path)
    L.run(cases_dir, tmp_path / "out", "", None, _fake_predictor, shuffle=False)
    calls = []
    L.run(cases_dir, tmp_path / "out", "", None, lambda i, d: calls.append(i), shuffle=False)
    assert calls == []



def test_the_majority_reference_answers_each_field_with_its_familys_commonest_gold():
    schema = {"x": {"type": "boolean", "description": "d"}}
    cases = [core.Case(id=f"fam-{i}", modality="decide", prompt="p", params={"schema": schema},
                       assertions={"answers": {"x": gold}}) for i, gold in enumerate((True, True, False))]
    rows = L.majority(cases)
    assert [r["passed"] for r in rows] == [True, True, False]
    s = L.summarize(rows)
    assert s["brier"] is None and s["ece"] is None
