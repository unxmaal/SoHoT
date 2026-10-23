"""A fenced diff closes at a ``` line outside a hunk's counted lines, never at one inside a hunk line. #1131."""
import json
from pathlib import Path

import pytest

from evals import repo
from tests.test_repo_lane import BASE_FILES, BUGGY, DARWIN, FIXED, HIDDEN, _diff, _here, _two_commits

FIXTURES = Path(__file__).parent / "fixtures" / "repo_fence_1131"
STORED = sorted(p.stem for p in FIXTURES.glob("*.json"))
README = "# pkg\n\nRun it:\n\n```\npkg run\n```\n\nadd() adds.\n"
NEW_README = "# pkg\n\nRun it:\n\n```bash\npkg run --all\n```\n\nadd() adds two numbers.\n"
DOC = _diff(README, NEW_README, "README.md")
CODE = _diff(BUGGY, FIXED)


def test_the_three_stored_replies_are_the_ones_named():
    assert STORED == ["opus-467--sohot-371-spec", "opus-467--sohot-371-symptom", "ornith-921c--sohot-371-symptom"]


@pytest.mark.parametrize("name", STORED)
def test_a_stored_reply_cut_at_a_readme_fence_now_extracts_whole(name):
    row = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    lines = row["reply"].splitlines(keepends=True)
    assert lines[0].startswith("```") and lines[-1].rstrip() == "```"
    whole = "".join(lines[1:-1])
    got = repo.extract_diff(row["reply"])
    assert got == whole
    assert whole.startswith(row["stored_diff"].rstrip("\n")) and len(row["stored_diff"]) < len(whole)
    assert any(ln[:1] in " +-" and "```" in ln for ln in got.splitlines())


def test_a_diff_that_adds_a_code_fence_to_a_readme_extracts_whole():
    assert "+```bash\n" in DOC and " ```\n" in DOC
    reply = f"Here is the fix.\n\n```diff\n{DOC}{CODE}```\n\nThat changes the README too.\n"
    assert repo.extract_diff(reply) == DOC + CODE


def test_a_fence_inside_a_hunk_line_does_not_close_the_block():
    diff = ("--- a/ci.yml\n+++ b/ci.yml\n@@ -1,3 +1,3 @@\n   run: |\n"
            "     echo '```'\n-    old\n+    new\n")
    assert repo.extract_diff(f"```diff\n{diff}```\n") == diff


def test_a_context_line_that_is_a_fence_counts_as_hunk_content():
    diff = "--- a/R.md\n+++ b/R.md\n@@ -1,3 +1,3 @@\n ```\n-a\n+b\n ```\n"
    assert repo.extract_diff(f"```diff\n{diff}```\n") == diff
    assert repo.extract_diff(f"```diff\n{diff}  ```\nnot the diff\n") == diff


def test_a_closer_past_an_overstated_hunk_still_closes():
    diff = "--- a/x\n+++ b/x\n@@ -1,9 +1,9 @@\n-a\n+b\n"
    assert repo.extract_diff(f"```diff\n{diff}```\nWait, more prose.\n") == diff


def test_the_closer_of_an_earlier_code_block_is_not_an_opener():
    diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    reply = f"Look:\n```python\nprint(1)\n```\nso:\n```diff\n{diff}```\n"
    assert repo.extract_diff(reply) == diff


def test_the_first_fenced_diff_wins_and_other_languages_are_passed_over():
    first = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n"
    second = "--- a/y\n+++ b/y\n@@ -1 +1 @@\n-c\n+d\n"
    reply = f"```python\n--- a/z\n```\n```patch\n{first}```\nor\n```diff\n{second}```\n"
    assert repo.extract_diff(reply) == first


def test_a_reply_cut_inside_its_fence_keeps_what_it_has():
    diff = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-a\n+b\n"
    assert repo.extract_diff(f"```diff\n{diff}") == diff


def test_no_newline_markers_are_hunk_lines_and_count_nothing():
    diff = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n-a\n\\ No newline at end of file\n+b\n ```\n"
    assert repo.extract_diff(f"```diff\n{diff}```\n") == diff


def test_a_blank_line_in_a_hunk_is_a_context_line():
    diff = "--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n\n-a\n+b\n"
    assert repo.extract_diff(f"```diff\n{diff}  ```\nprose\n") == diff


def test_a_range_without_a_count_is_one_line():
    diff = "--- a/R.md\n+++ b/R.md\n@@ -4 +4 @@\n ```\n"
    assert repo.extract_diff(f"```diff\n{diff}```\n") == diff


@DARWIN
def test_regrade_reextract_grades_the_diff_extracted_today(tmp_path, monkeypatch, capsys):
    import yaml

    from harness import cli
    case = _two_commits(tmp_path / "upstream", {**BASE_FILES, "README.md": README},
                        {"pkg/mod.py": FIXED, "tests/test_mod.py": HIDDEN, "README.md": NEW_README})
    (tmp_path / "cases" / "repo").mkdir(parents=True)
    raw = {"id": "fixture", "modality": "repo", "prompt": case.prompt, "params": case.params}
    (tmp_path / "cases" / "repo" / "fixture.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    reply = f"```diff\n{DOC}{CODE}```\n"
    cut = DOC[:DOC.index("```")]
    run = tmp_path / "run"
    run.mkdir()
    stored = {"case": "fixture", "reply": reply, "diff": cut, "grade": {"resolved": False, "patch_applied": False}}
    (run / "cand--fixture.json").write_text(json.dumps(stored), encoding="utf-8")
    same = {"case": "fixture", "reply": reply, "diff": DOC + CODE, "grade": {"resolved": True, "patch_applied": True}}
    (run / "cand2--fixture.json").write_text(json.dumps(same), encoding="utf-8")
    before = (run / "cand--fixture.json").read_bytes()
    monkeypatch.setattr(repo, "prepare", _here)
    base = ["cases", "regrade", "repo", "--json", "--run", str(run), "--out", str(tmp_path / "cases")]
    assert cli.main(base) == 0
    old = json.loads(capsys.readouterr().out)["regraded"]
    assert [(r["file"], r["resolved"]) for r in old] == [("cand--fixture.json", False), ("cand2--fixture.json", True)]
    assert cli.main([*base, "--reextract"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["unchanged"] == 1
    assert [(r["file"], r["was_resolved"], r["resolved"]) for r in out["regraded"]] == [
        ("cand--fixture.json", False, True)]
    assert out["regraded"][0]["lines"] > out["regraded"][0]["stored_lines"]
    assert (run / "cand--fixture.json").read_bytes() == before


def test_past_an_undercounted_hunk_only_a_bare_fence_line_closes():
    diff = "--- a/ci.yml\n+++ b/ci.yml\n@@ -1 +1 @@\n-a\n+b\n+echo '```'\n"
    assert repo.extract_diff(f"```diff\n{diff}```\n") == diff
