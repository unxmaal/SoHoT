"""The repo-lane failure taxonomy reads run directories, checks every cited excerpt, and reads each arm back. #921."""
import json

import pytest

from evals.analysis import repo_failures as F

REPLY = "I'll start by exploring the repository.<tool_call>\n<function=command>"


def _row(case, passed=False, cls="invalid_patch"):
    return {"case_id": case, "candidate": "org/x", "passed": passed, "failure_class": "" if passed else cls}


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "20261018-210000-000-0000-repo"
    d.mkdir()
    rows = [_row("a", True), _row("b", cls="token_budget_exhausted"), _row("c"), _row("d"),
            _row("e", cls="content_failed"), _row("f", cls="environment_error")]
    requests = {"org/x": [{"max_tokens": 32768, "sampling": {"temperature": 0.2},
                           "template": {"enable_thinking": False}, "system_sha": "abc"}]}
    (d / "results.json").write_text(json.dumps({"receipt": {
        "modality": "repo", "case_ids": list("abcdef"), "max_tokens": 32768,
        "template": {"repo": {"enable_thinking": False}}, "sampling": {"repo": {"temperature": 0.2}},
        "requests": requests}, "rows": rows}), encoding="utf-8")
    (d / "org_x--c.json").write_text(json.dumps({"case": "c", "reply": REPLY}), encoding="utf-8")
    return d


def _label(run_dir, case="c", cls="tool_call", text="<tool_call>", **kw):
    f = run_dir / "org_x--c.json"
    (at,) = F.locate(f, text)
    return {"run": run_dir.name, "case": case, "class": cls, "file": f.name, "offset": at,
            "excerpt": text, **kw}


def _write(path, labels):
    path.write_text("".join(json.dumps(x) + "\n" for x in labels), encoding="utf-8")
    return path


def test_the_tally_counts_each_runner_class(run_dir):
    got = F.tally(F.load_run(run_dir))
    assert [got[c] for c in F.TALLY] == [1, 1, 0, 2, 1, 1]


def test_a_paused_run_is_tallied_from_its_checkpoint(tmp_path):
    d = tmp_path / "paused"
    d.mkdir()
    (d / "checkpoint.jsonl").write_text(
        json.dumps({"identity": {"modality": "repo"}}) + "\n"
        + "".join(json.dumps({"row": _row(c)}) + "\n" for c in "xy"), encoding="utf-8")
    run = F.load_run(d)
    assert run.receipt["modality"] == "repo" and F.tally(run)["invalid_patch"] == 2


def test_an_excerpt_is_checked_at_its_byte_offset(run_dir):
    good = _label(run_dir)
    assert F.check_excerpt(run_dir, good) == ""
    assert "not the cited excerpt" in F.check_excerpt(run_dir, {**good, "offset": good["offset"] + 1})
    assert "outside" in F.check_excerpt(run_dir, {**good, "file": "../elsewhere.json"})
    assert "is not in" in F.check_excerpt(run_dir, {**good, "file": "org_x--zz.json"})


def test_a_non_ascii_excerpt_is_found_by_bytes_not_characters(run_dir):
    f = run_dir / "org_x--c.json"
    f.write_bytes("café — then <tool_call>".encode("utf-8"))
    lab = _label(run_dir)
    assert lab["offset"] == len("café — then ".encode("utf-8"))
    assert F.check_excerpt(run_dir, lab) == ""


def test_every_failing_row_but_an_environment_error_needs_a_label(run_dir, tmp_path):
    labels = F.load_labels(_write(tmp_path / "l.jsonl", [_label(run_dir)]))
    assert F.unlabelled(F.load_run(run_dir), labels) == ["b", "d", "e"]


def test_the_command_fails_on_a_bad_excerpt_and_with_complete_on_a_gap(run_dir, tmp_path, capsys):
    good = _write(tmp_path / "good.jsonl", [_label(run_dir)])
    assert F.main(["tally", str(run_dir), "--labels", str(good)]) == 0
    assert F.main(["tally", str(run_dir), "--labels", str(good), "--complete"]) == 1
    bad = _write(tmp_path / "bad.jsonl", [{**_label(run_dir), "offset": 0}])
    assert F.main(["tally", str(run_dir), "--labels", str(bad)]) == 1
    assert "excerpt" in capsys.readouterr().err


@pytest.mark.parametrize("extra, why", [
    ({"class": "vibes"}, "codebook"),
    ({"class": "budget_exhausted"}, "at_cut"),
])
def test_a_label_off_the_codebook_is_refused(run_dir, tmp_path, extra, why):
    with pytest.raises(ValueError, match=why):
        F.load_labels(_write(tmp_path / "l.jsonl", [{**_label(run_dir), **extra}]))


def test_every_class_names_whose_fault_it_is():
    assert set(F.CODEBOOK.values()) <= {"model", "protocol", "harness"}
    assert F.CODEBOOK["budget_exhausted"] == "harness" and F.CODEBOOK["tool_call"] == "protocol"


def test_kappa_is_one_for_agreement_and_zero_at_chance():
    a = [{"run": "r", "case": c, "class": k} for c, k in zip("abcd", ["x", "x", "y", "y"])]
    assert F.kappa(a, a) == (1.0, 4)
    flipped = [{**x, "class": {"x": "y", "y": "x"}[x["class"]]} for x in a]
    assert F.kappa(a, flipped)[0] == pytest.approx(-1.0)
    half = [{**x, "class": k} for x, k in zip(a, ["x", "y", "x", "y"])]
    assert F.kappa(a, half)[0] == pytest.approx(0.0)
    assert F.kappa(a, []) == (None, 0)


def test_the_blind_sample_is_seeded_and_skips_passes_and_environment_errors(run_dir):
    runs = [F.load_run(run_dir)]
    got = F.sample(runs, 3, 921)
    assert got == F.sample(runs, 3, 921) and len(got) == 3
    assert {case for _, case in got} <= {"b", "c", "d", "e"}


def test_an_arm_is_read_back_from_what_was_sent_not_from_its_name(run_dir):
    receipt = F.load_run(run_dir).receipt
    assert F.arm_check(receipt, "B") == []
    wrong = F.arm_check(receipt, "A")
    assert any("template" in w for w in wrong)
    assert any("max_tokens" in w for w in F.arm_check(
        {"requests": {"k": [{**receipt["requests"]["org/x"][0], "max_tokens": 4000}]}}, "B"))
    assert "predates" in F.arm_check({}, "C")[0]


def test_the_receipt_command_fails_an_arm_that_did_not_run_as_labelled(run_dir, capsys):
    assert F.main(["receipt", str(run_dir), "--arm", "B"]) == 0
    assert "enable_thinking" in capsys.readouterr().out
    assert F.main(["receipt", str(run_dir), "--arm", "C"]) == 1


def test_the_committed_labels_parse_against_the_codebook():
    for lab in F.load_labels():
        assert lab["class"] in F.CODEBOOK
    blind = F.load_labels(F.LABELS.with_name("repo_failure_labels_blind.jsonl"))
    assert blind and {(x["run"], x["case"]) for x in blind} <= {(x["run"], x["case"]) for x in F.load_labels()}


@pytest.mark.parametrize("arm", sorted(F.ARMS))
def test_each_arm_command_is_one_evals_run_accepts_and_reads_back_as_itself(arm):
    from evals import run as R
    from harness import serving
    argv = F.arm_command(arm, "/tmp/out")
    args = R.parse_args(argv[argv.index("evals.run") + 1:])
    assert args.modality == "repo" and args.repeat == 1 and args.split == "all"
    (spec,) = R.split_candidates(args.candidates)
    want = F.expected(arm)
    assert R.effective_template("repo", [spec]).get("repo", {}) == want["template"]
    sent = {"template": want["template"], "sampling": want["sampling"],
            "max_tokens": want["max_tokens"][-1], "system_sha": "x"}
    assert F.arm_check({"requests": {"k": [sent]}}, arm) == []
    assert serving.route(spec, "http://gw").template == want["template"]


def test_the_arms_differ_in_one_thing_each_from_the_control():
    a, b, c = (F.expected(x) for x in "ABC")
    assert a["template"] == {} and a["sampling"] == {"temperature": 0.2} and a["max_tokens"] == (32768,)
    assert b == {**a, "template": {"enable_thinking": False}}
    assert c["template"] == {"enable_thinking": True} and c["max_tokens"] == (32768, 65536)
    assert c["sampling"] == {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.0,
                             "presence_penalty": 0.0}


def test_a_run_that_kept_no_reasoning_is_labelled_budget_exhausted_unrecorded(run_dir, tmp_path):
    (lab,) = F.load_labels(_write(tmp_path / "l.jsonl", [_label(run_dir, cls="budget_exhausted", at_cut="unrecorded")]))
    assert lab["at_cut"] == "unrecorded"


def test_the_recount_header_defect_is_charged_to_the_harness():
    assert F.CODEBOOK["recount_header"] == "harness"


def test_every_class_has_a_definition_and_one_precedence_place(capsys):
    assert set(F.DEFINITIONS) == set(F.CODEBOOK) == set(F.PRECEDENCE)
    assert len(F.PRECEDENCE) == len(set(F.PRECEDENCE))
    assert F.main(["codebook"]) == 0
    out = capsys.readouterr().out
    assert all(f"{c} ({F.CODEBOOK[c]})" in out for c in F.CODEBOOK)
    assert out.index("tool_call") < out.index("wrong_fix")


def test_a_stratified_sample_takes_from_every_stratum_and_skips_what_it_is_told(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    rows = ([_row(f"i{n}") for n in range(20)] + [_row(f"c{n}", cls="content_failed") for n in range(2)]
            + [_row(f"t{n}", cls="token_budget_exhausted") for n in range(5)])
    (d / "results.json").write_text(json.dumps({"receipt": {}, "rows": rows}), encoding="utf-8")
    runs = [F.load_run(d)]
    got = F.sample(runs, 6, 921, stratify=True, skip=("token_budget_exhausted",))
    assert got == F.sample(runs, 6, 921, stratify=True, skip=("token_budget_exhausted",))
    cases = [c for _, c in got]
    assert len(cases) == 6 and sum(c.startswith("c") for c in cases) == 2
    assert not any(c.startswith("t") for c in cases)
    assert len(F.sample(runs, 100, 921, stratify=True)) == 27


def test_kappa_names_each_row_the_labellers_disagree_on(tmp_path, capsys):
    a = [{"run": "r", "case": c, "class": "wrong_fix", "file": "f", "offset": 0, "excerpt": "x"} for c in "ab"]
    b = [a[0], {**a[1], "class": "regression"}]
    assert F.disagreements(a, b) == [("r", "b", "wrong_fix", "regression")]
    assert F.main(["kappa", str(_write(tmp_path / "a.jsonl", a)), str(_write(tmp_path / "b.jsonl", b))]) == 0
    assert "r b: wrong_fix / regression" in capsys.readouterr().out


def _regrade(run_dir, case, resolved, detail=""):
    return {"run": run_dir.name, "file": f"org_x--{case}.json", "case": case, "resolved": resolved,
            "patch_applied": True, "detail": detail}


def test_a_row_its_regrade_resolved_needs_no_label_and_must_not_keep_one(run_dir, tmp_path, capsys):
    regrades = _write(tmp_path / "r.jsonl", [_regrade(run_dir, "d", True)])
    labels = [_label(run_dir), _label(run_dir, case="b", cls="budget_exhausted", at_cut="unrecorded"),
              _label(run_dir, case="e", cls="wrong_fix")]
    good = _write(tmp_path / "good.jsonl", labels)
    assert F.unlabelled(F.load_run(run_dir), F.load_labels(good), F.load_regrades(regrades)) == []
    assert F.main(["tally", str(run_dir), "--labels", str(good), "--regrades", str(regrades), "--complete"]) == 0
    assert "now resolved: d" in capsys.readouterr().out
    kept = _write(tmp_path / "kept.jsonl", [*labels, _label(run_dir, case="d", cls="recount_header")])
    assert F.main(["tally", str(run_dir), "--labels", str(kept), "--regrades", str(regrades)]) == 1
    assert "its regrade resolved" in capsys.readouterr().err


def test_a_label_may_cite_its_rows_regrade_detail(run_dir, tmp_path):
    again = _regrade(run_dir, "c", False, "fail_to_pass still failing: t")
    regrades = F.load_regrades(_write(tmp_path / "r.jsonl", [again]))
    lab = {"run": run_dir.name, "case": "c", "class": "wrong_fix", "file": "org_x--c.json", "regrade": True,
           "offset": 0, "excerpt": "fail_to_pass still failing"}
    assert F.check_excerpt(run_dir, lab, regrades) == ""
    assert "not the cited excerpt" in F.check_excerpt(run_dir, {**lab, "offset": 1}, regrades)
    assert F.check_excerpt(run_dir, {**lab, "case": "d"}, regrades) == "no regrade of this row"


def test_every_committed_label_that_cites_a_regrade_has_one():
    regrades = F.load_regrades()
    cited = [x for x in F.load_labels() + F.load_labels(F.LABELS.with_name("repo_failure_labels_blind.jsonl"))
             if x.get("regrade")]
    assert cited and all((x["run"], x["case"]) in regrades for x in cited)
    model = {(x["run"], x["case"]) for x in F.load_labels() if F.GRADINGS.get(x.get("grading")) in (None, "model")}
    assert not any(g["resolved"] and (r, c) in model for (r, c), g in regrades.items())


def _case(d, case, **stored):
    (d / f"org_x--{case}.json").write_text(json.dumps({"case": case, **stored}), encoding="utf-8")


@pytest.fixture
def rerun(tmp_path):
    d = tmp_path / "921-arm-a"
    d.mkdir()
    rows = [_row("ok", True), _row("cut", cls="token_budget_exhausted"), _row("tool"), _row("hunk"), _row("ctx"),
            _row("new"), _row("wrong", cls="content_failed"), _row("env", cls="environment_error")]
    details = {"tool": "the reply holds no diff", "hunk": "git apply: error: No valid patches in input",
               "ctx": "git apply: error: patch failed: harness/x.py:50\nerror: harness/x.py: patch does not apply",
               "new": "git apply: error: new file harness/v58.py depends on old contents",
               "wrong": "fail_to_pass still failing: tests/test_x.py::test_y"}
    for r in rows:
        r["detail"] = details.get(r["case_id"], "")
    (d / "results.json").write_text(json.dumps({"receipt": {}, "rows": rows}), encoding="utf-8")
    _case(d, "tool", reply=REPLY, diff="")
    _case(d, "hunk", reply="x", diff="--- a/x.py\n+++ b/x.py\n@@ def add(argv: list[str]):\n-a\n+b\n")
    _case(d, "ctx", reply="x", diff="--- a/x.py\n+++ b/x.py\n@@ -50,1 +50,1 @@\n-a\n+b\n")
    _case(d, "new", reply="x", diff="--- a/harness/v58.py\n+++ b/harness/v58.py\n@@ -0,0 +1,1 @@\n+a\n")
    _case(d, "wrong", reply="x", diff="--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n")
    (d / "org_x--cut.trajectory.json").write_text(json.dumps({"requests": [
        {"finish_reason": "length", "reasoning": "Let me look at the \"files\".\nLet me look at the \"files\".\n"}]}),
        encoding="utf-8")
    return d


def test_a_new_file_written_against_old_contents_is_a_missing_file():
    row = {"failure_class": "invalid_patch", "detail": "git apply: error: new file v58.py depends on old contents"}
    assert F.cause(row, {"diff": "--- a/v58.py\n+++ b/v58.py\n@@ -0,0 +1 @@\n+a\n"}) == "missing_file"
    assert F.CODEBOOK["missing_file"] == "model" and "missing_file" in F.PRECEDENCE


def test_propose_labels_every_failing_row_with_an_excerpt_the_tally_accepts(rerun):
    run = F.load_run(rerun)
    got = F.propose(run, {"cut": ("looping", 'Let me look at the "files".')})
    assert {x["case"]: x["class"] for x in got} == {
        "cut": "budget_exhausted", "tool": "tool_call", "hunk": "malformed_hunk", "ctx": "context_mismatch",
        "new": "missing_file", "wrong": "wrong_fix"}
    assert all(F.check_excerpt(rerun, x) == "" for x in got)
    assert F.unlabelled(run, got) == []
    (cut,) = [x for x in got if x["case"] == "cut"]
    assert cut["at_cut"] == "looping" and cut["file"] == "org_x--cut.trajectory.json"


def test_propose_labels_a_regraded_row_from_its_regrade(rerun, tmp_path):
    run = F.load_run(rerun)
    regrades = F.load_regrades(_write(tmp_path / "r.jsonl", [
        _regrade(rerun, "ctx", False, "fail_to_pass still failing: tests/test_x.py::test_y"),
        _regrade(rerun, "new", True)]))
    got = {x["case"]: x for x in F.propose(run, {"cut": ("looping", 'Let me look at the "files".')}, regrades)}
    assert got["ctx"]["class"] == "wrong_fix" and got["ctx"]["regrade"] is True
    assert "new" not in got
    assert all(F.check_excerpt(rerun, x, regrades) == "" for x in got.values())
    assert F.unlabelled(run, list(got.values()), regrades) == []


def test_a_budget_row_no_labeller_read_is_left_unlabelled(rerun):
    run = F.load_run(rerun)
    assert F.unlabelled(run, F.propose(run, {})) == ["cut"]
    with pytest.raises(ValueError, match="not in"):
        F.propose(run, {"cut": ("looping", "words the reasoning never says")})


def test_the_propose_command_prints_labels_the_codebook_accepts(rerun, tmp_path, capsys):
    cuts = _write(tmp_path / "cuts.jsonl", [{"run": rerun.name, "case": "cut", "at_cut": "other",
                                             "excerpt": 'Let me look at the "files".'}])
    assert F.main(["propose", str(rerun), "--at-cut", str(cuts)]) == 0
    out = tmp_path / "labels.jsonl"
    out.write_text(capsys.readouterr().out, encoding="utf-8")
    assert len(F.load_labels(out)) == 6
