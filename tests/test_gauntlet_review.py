"""`soh gauntlet review`: the review questions a diff raises, for classes no detector can find (#492 D)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.gauntlet import classes, core, review

REPO = Path(__file__).resolve().parent.parent

SKILL = """\
# The corpus

## A statistic blind to the effect under test

**Bitten:** 1.

**Trigger:** is a summary statistic standing in for the thing being measured?
Could it stay the same while the effect changes?

**Tier:** 3. This one cannot be automated.

**Test shape:** none. Ask the question before running the experiment.

## A closed table fronting an open set

**Trigger:** is there a dict keyed on something an outside party names?

**Tier:** 2.

**Test shape:** feed a key that is not in the table.
"""


def test_the_snapshot_carries_each_class_s_trigger_and_test_shape_on_one_line():
    snap = core.parse_skill(SKILL, "SKILL.md")
    assert snap[0]["trigger"] == ("is a summary statistic standing in for the thing being measured? "
                                  "Could it stay the same while the effect changes?")
    assert snap[0]["test_shape"] == "none. Ask the question before running the experiment."
    assert snap[1]["trigger"].startswith("is there a dict keyed")


def test_the_committed_snapshot_has_a_trigger_for_every_class():
    missing = [c["id"] for c in core.load_snapshot() if not c.get("trigger") or not c.get("test_shape")]
    assert not missing


DIFF = """\
diff --git a/harness/rank.py b/harness/rank.py
index 1..2 100644
--- a/harness/rank.py
+++ b/harness/rank.py
@@ -10,0 +11,3 @@ def score(rows):
+    mean = statistics.mean(r.score for r in rows)
+    return mean
+# a comment
@@ -40 +43 @@ def other():
-    old = 1
+    new = 2
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-x
+the median of the pass rate
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-mean = 1
"""


def test_added_lines_are_read_with_their_new_line_numbers():
    got = review.added_lines(DIFF)
    assert got["harness/rank.py"] == [(11, "    mean = statistics.mean(r.score for r in rows)"),
                                      (12, "    return mean"), (13, "# a comment"), (43, "    new = 2")]
    assert got["README.md"] == [(1, "the median of the pass rate")]
    assert "gone.py" not in got


SNAP = [{"id": "stat", "heading": "A statistic blind", "tier": 3, "trigger": "is a summary standing in?",
         "test_shape": "none. Ask it."},
        {"id": "table", "heading": "A closed table", "tier": 2, "trigger": "a dict?", "test_shape": "feed a key"},
        {"id": "seam", "heading": "The seam", "tier": 2, "trigger": "a boundary?", "test_shape": "both sides"},
        {"id": "scan", "heading": "Scanned", "tier": 1, "trigger": "t", "test_shape": "s"}]
INDEX = {"stat": {"review": r"\b(mean|median)\b", "review_paths": r"\.py$"},
         "table": {"detector": "closed_tables", "review": r"\{"},
         "seam": {"review": r"subprocess"},
         "scan": {"review": r"mean"}}


def test_a_class_fires_on_an_added_line_its_heuristic_matches_in_a_file_it_covers():
    fired = review.fire(review.added_lines(DIFF), INDEX, SNAP)
    assert [f["id"] for f in fired] == ["stat"]
    assert fired[0]["where"] == ["harness/rank.py:11", "harness/rank.py:12"]
    assert fired[0]["trigger"] == "is a summary standing in?" and fired[0]["test_shape"] == "none. Ask it."


def test_a_class_with_a_detector_or_a_scanner_tier_is_never_a_review_question():
    changed = {"harness/x.py": [(1, "{ mean subprocess")]}
    assert [f["id"] for f in review.fire(changed, INDEX, SNAP)] == ["stat", "seam"]


def test_nothing_fires_on_a_diff_no_heuristic_matches():
    assert review.fire({"harness/x.py": [(1, "x = 1")]}, INDEX, SNAP) == []


def test_the_rendering_asks_the_trigger_and_names_the_test_shape():
    text = review.render(review.fire(review.added_lines(DIFF), INDEX, SNAP))
    assert "A statistic blind (tier 3)" in text
    assert "ask: is a summary standing in?" in text and "test: none. Ask it." in text
    assert "harness/rank.py:11" in text
    assert review.render([]) .startswith("no review questions")


def test_every_review_only_class_here_has_a_heuristic():
    snap = {c["id"]: c for c in core.load_snapshot()}
    missing = [cid for cid, e in classes.INDEX.items()
               if review.review_only(cid, e, snap.get(cid, {})) and not e.get("review")]
    assert not missing, "a review-only class needs a `review` regex in classes.INDEX: " + ", ".join(missing)


def test_every_heuristic_fires_on_something_and_not_on_everything():
    for cid, e in classes.INDEX.items():
        if not e.get("review"):
            continue
        rx = re.compile(e["review"])
        assert not rx.search("x = 1"), f"{cid}: its review heuristic fires on a bare assignment"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8")


def test_the_review_command_reads_a_git_range(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("no git")
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "t@example.org", cwd=tmp_path)
    _git("config", "user.name", "t", cwd=tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git("add", "a.py", cwd=tmp_path)
    _git("commit", "-qm", "one", cwd=tmp_path)
    (tmp_path / "a.py").write_text("x = 1\nm = statistics.median(xs)\n", encoding="utf-8")
    _git("commit", "-qam", "two", cwd=tmp_path)
    got = review.changed(tmp_path, "HEAD~1...HEAD")
    assert got == {"a.py": [(2, "m = statistics.median(xs)")]}


def test_python_m_tests_gauntlet_review_runs():
    out = subprocess.run([sys.executable, "-m", "tests.gauntlet", "review", "HEAD...HEAD"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("no review questions")


def test_only_code_lines_in_production_code_are_read_unless_a_class_names_its_paths():
    index = {"seam": {"review": r"subprocess"}}
    changed = {"README.md": [(1, "subprocess")], "harness/a.py": [(1, "# subprocess"), (2, "subprocess.run(x)")],
               "tests/test_a.py": [(1, "subprocess.run(x)")], "evals/cases/agent/x.py": [(1, "subprocess")]}
    assert review.fire(changed, index, SNAP)[0]["where"] == ["harness/a.py:2"]
    index["seam"]["review_paths"] = r"^tests/"
    assert review.fire(changed, index, SNAP)[0]["where"] == ["tests/test_a.py:1"]


INNOCENT = ["import os", "from harness import paths", "def f(a, b=None):", "    return x", "    if not rows:",
            "for r in rows:", "    out.append(r)", "class Thing:", "    \"\"\"One line of prose.\"\"\"",
            "name = row[\"name\"]", "    conn.close()", "with open(p, encoding=\"utf-8\") as f:",
            "    print(msg, file=sys.stderr)", "    candidate = spec", "rows = conn.execute(q).fetchall()"]


def test_no_heuristic_fires_on_ordinary_lines():
    noisy = {cid: [line for line in INNOCENT if re.search(e["review"], line)]
             for cid, e in classes.INDEX.items() if e.get("review")}
    assert not {cid: hit for cid, hit in noisy.items() if hit}
