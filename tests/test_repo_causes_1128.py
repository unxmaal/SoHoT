"""`repo_failures causes` reads each row's class off its reply and grade and counts it by case group. #1128."""
import json

import pytest

from evals.analysis import repo_failures as F

RANGED = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n a\n-b\n+c\n"
RANGELESS = "--- a/x.py\n+++ b/x.py\n@@ def f():\n a\n-b\n+c\n"
#: case -> (runner class, detail, stored reply, stored diff, prompt tokens, completion tokens); None: no case file.
ROWS = {
    "h-pass": ("", "", "ok", RANGED, 100, 50),
    "h-cut": ("token_budget_exhausted", "spent the whole budget on reasoning", None, None, 200, 32768),
    "h-cutans": ("token_budget_exhausted", "git apply: error: patch failed: x.py:1", "Here:\n" + RANGED, RANGED,
                 300, 32768),
    "m-tool": ("invalid_patch", "the reply holds no diff", "Let me look.<tool_call>\n<function=command>", "",
               400, 60),
    "m-prose": ("invalid_patch", "the reply holds no diff", "I cannot do this.", "", 500, 70),
    "m-garbage": ("invalid_patch", "git apply: error: patch with only garbage at <stdin>:4", RANGELESS,
                  RANGELESS, 600, 80),
    "m-rangeless": ("invalid_patch", "git apply: error: patch failed: x.py:1", RANGELESS, RANGELESS, 700, 90),
    "t-context": ("invalid_patch", "git apply: error: patch failed: x.py:1", RANGED, RANGED, 800, 100),
    "t-wrong": ("content_failed", "fail_to_pass still failing: tests/test_x.py::test_a", RANGED, RANGED, 900, 110),
    "t-regress": ("content_failed", "pass_to_pass broken: tests/test_x.py::test_b", RANGED, RANGED, 1000, 120),
    "t-env": ("environment_error", "environment: the mirror could not be fetched", None, None, None, None),
}
GROUP = {"h": "history", "m": "history_mcm_engine", "t": "transcripts"}


@pytest.fixture
def cases_root(tmp_path):
    root = tmp_path / "cases" / "repo"
    for case in ROWS:
        d = root / GROUP[case[0]]
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{case}.yaml").write_text(f"id: {case}\n", encoding="utf-8")
    (root / "top.yaml").write_text("id: top\n", encoding="utf-8")
    return root


def _run(tmp_path, name, rows):
    d = tmp_path / name
    d.mkdir()
    out = []
    for case, (fc, detail, reply, diff, prompt, completion) in rows.items():
        out.append({"case_id": case, "candidate": "org/x", "passed": not fc, "failure_class": fc, "detail": detail})
        if reply is not None:
            (d / f"org_x--{case}.json").write_text(json.dumps({"case": case, "reply": reply, "diff": diff}),
                                                   encoding="utf-8")
        if prompt is not None:
            finish = "length" if completion == 32768 else "stop"
            (d / f"org_x--{case}.trajectory.json").write_text(json.dumps({"requests": [
                {"prompt_tokens": 1, "completion_tokens": 1, "finish_reason": "stop"},
                {"prompt_tokens": prompt, "completion_tokens": completion, "finish_reason": finish}]}),
                encoding="utf-8")
    (d / "results.json").write_text(json.dumps({"receipt": {"modality": "repo"}, "rows": out}), encoding="utf-8")
    return d


def test_each_row_gets_the_class_it_failed_at(tmp_path, cases_root):
    run = F.load_run(_run(tmp_path, "r", ROWS))
    got = {r["case"]: r["cause"] for r in F.causes(run, F.case_groups(cases_root))}
    assert got == {"h-pass": "pass", "h-cut": "budget_no_answer", "h-cutans": "budget_cut_answer",
                   "m-tool": "tool_call", "m-prose": "no_diff", "m-garbage": "malformed_hunk",
                   "m-rangeless": "malformed_hunk", "t-context": "context_mismatch", "t-wrong": "wrong_fix",
                   "t-regress": "regression", "t-env": "environment_error"}


def test_tokens_come_from_the_last_request_of_the_trajectory(tmp_path, cases_root):
    run = F.load_run(_run(tmp_path, "r", ROWS))
    got = {r["case"]: r for r in F.causes(run, F.case_groups(cases_root))}
    assert (got["h-cut"]["prompt_tokens"], got["h-cut"]["completion_tokens"], got["h-cut"]["finish"]) == \
        (200, 32768, "length")
    assert got["t-env"]["prompt_tokens"] is None


def test_a_case_is_grouped_by_its_directory_and_an_old_run_wins(cases_root):
    groups = F.case_groups(cases_root, old={"m-tool"})
    assert (groups["h-pass"], groups["t-wrong"], groups["m-tool"], groups["m-prose"], groups["top"]) == \
        ("history", "transcripts", "old", "history_mcm_engine", "repo")


def test_the_table_counts_causes_and_reports_cut_share_and_medians(tmp_path, cases_root):
    run = F.load_run(_run(tmp_path, "r", ROWS))
    lines = F.cause_table(F.causes(run, F.case_groups(cases_root))).splitlines()
    assert lines[0] == "| cause | history | history_mcm_engine | transcripts | total |"
    row = {line.split(" | ")[0].lstrip("| "): line for line in lines[2:]}
    assert row["pass"] == "| pass | 1 | 0 | 0 | 1 |"
    assert row["malformed_hunk"] == "| malformed_hunk | 0 | 2 | 0 | 2 |"
    assert row["rows"] == "| rows | 3 | 4 | 4 | 11 |"
    assert row["cut %"] == "| cut % | 67 | 0 | 0 | 18 |"
    assert row["median prompt tokens"] == "| median prompt tokens | 200 | 550 | 900 | 550 |"
    assert row["median completion, uncut"] == "| median completion, uncut | 50 | 75 | 110 | 85 |"


def test_the_cli_prints_one_table_per_run_with_old_cases_split_out(tmp_path, cases_root, capsys):
    run = _run(tmp_path, "new", ROWS)
    old = _run(tmp_path, "old", {"h-pass": ROWS["h-pass"], "h-cut": ROWS["h-cut"]})
    assert F.main(["causes", str(run), "--old", str(old), "--cases", str(cases_root), "--rows"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("new\n\n| cause | history | history_mcm_engine | old | transcripts | total |")
    assert "| budget_no_answer | 0 | 0 | 1 | 0 | 1 |" in out
    assert "tool_call\thistory_mcm_engine\tm-tool\t400\t60" in out
