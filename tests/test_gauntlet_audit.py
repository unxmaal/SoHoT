"""Closing the loop: a defect closed without a class is found, offline in CI and by gh at a desk (#492)."""

import subprocess
from pathlib import Path

import pytest

from tests.gauntlet import classes, core

REPO = Path(__file__).resolve().parent.parent

SNAPSHOT = [
    {"id": "one-question-two-answers", "heading": "One question, two answers", "source": "SKILL.md", "tier": 1},
    {"id": "a-consumer-limits-before-it-filters-for-what-it-can-act-on",
     "heading": "A consumer limits before it filters for what it can act on", "source": "SKILL.md", "tier": 2},
    {"id": "encoding-assumed", "heading": "10. Encoding assumed", "source": "general-corpus.md", "tier": 1},
]

INDEX = {
    "one-question-two-answers": {"instances": [{"issue": 10}, {"issue": 30}, {"rule": 268}], "scanners": []},
    "a-consumer-limits-before-it-filters-for-what-it-can-act-on": {
        "instances": [{"issue": 20}], "scanners": []},
}
PENDING = {"guard-built-never-invoked": {"tier": 2, "instances": [{"issue": 40}, {"issue": 50}]}}
UNCLASSIFIED = {60: "upstream model behaviour"}

DEFECTS = {
    10: {"title": "a", "created": "2026-09-01T10:00:00Z"},
    20: {"title": "b", "created": "2026-09-02T10:00:00Z"},
    30: {"title": "c", "created": "2026-09-03T10:00:00Z"},
    40: {"title": "d", "created": "2026-09-04T10:00:00Z"},
    50: {"title": "e", "created": "2026-09-04T09:00:00Z"},
    60: {"title": "f", "created": "2026-09-05T10:00:00Z"},
}


@pytest.mark.parametrize("text, want", [
    ("Fixes #12", {12}),
    ("closes #12\nCloses #13", {12, 13}),
    ("Resolved: #7", {7}),
    ("fix #3 and fixed #4", {3, 4}),
    ("Part of #492", set()),
    ("Refs #5, see #6", set()),
    ("prefixes #9", set()),
])
def test_closing_references_are_read_the_way_github_reads_them(text, want):
    assert core.closing_refs(text) == want


def test_a_defect_no_class_names_is_unattributed():
    labelled = [10, 20, 30, 40, 50, 60, 70]
    assert core.unattributed(labelled, INDEX, PENDING, UNCLASSIFIED) == [70]


def test_an_unclassified_defect_is_explained_not_unattributed():
    assert 60 not in core.unattributed([60], INDEX, PENDING, UNCLASSIFIED)


def test_a_closing_reference_to_an_unbound_defect_fails():
    messages = ["Fixes #10", "Closes #70 the new one", "Fixes #80 not a defect"]
    found = core.unbound_closures(messages, {10, 70}, INDEX, PENDING, UNCLASSIFIED)
    assert found == [(70, "Closes #70 the new one")]


def test_a_closing_reference_to_a_bound_defect_passes():
    assert core.unbound_closures(["Fixes #20", "Closes #60"], {20, 60}, INDEX, PENDING, UNCLASSIFIED) == []


def test_stats_count_classes_per_tier_and_instances_per_class():
    s = core.stats(INDEX, PENDING, SNAPSHOT, DEFECTS)
    assert s["classes_per_tier"] == {1: 1, 2: 2}
    assert s["instances"]["one-question-two-answers"] == 2
    assert s["instances"]["guard-built-never-invoked"] == 2
    assert s["rules"]["one-question-two-answers"] == 1


def test_kill_rate_counts_only_defects_after_the_first_instance():
    s = core.stats(INDEX, PENDING, SNAPSHOT, DEFECTS)
    assert s["after_first"]["one-question-two-answers"] == 1
    assert s["after_first"]["a-consumer-limits-before-it-filters-for-what-it-can-act-on"] == 0
    assert s["after_first"]["guard-built-never-invoked"] == 1
    assert s["first"]["guard-built-never-invoked"] == "2026-09-04T09:00:00Z"
    assert s["kill_rate"] == pytest.approx(2 / 5)


def test_a_class_with_no_issue_instances_has_no_kill_rate_entry():
    index = {"encoding-assumed": {"instances": [{"rule": 244}], "scanners": []}}
    s = core.stats(index, {}, SNAPSHOT, DEFECTS)
    assert "encoding-assumed" not in s["after_first"]
    assert s["kill_rate"] is None


def test_the_report_names_the_gap_and_the_numbers():
    text = core.report(labelled=[10, 70], snapshot_numbers=set(DEFECTS), closures=[(70, "Fixes #70")],
                       index=INDEX, pending=PENDING, unclassified=UNCLASSIFIED,
                       snapshot=SNAPSHOT, defects=DEFECTS)
    assert "#70" in text and "no class" in text
    assert "not in the snapshot" in text
    assert "kill rate" in text
    assert "tier 1: 1" in text
    assert "tier 1 with no scanner yet: one-question-two-answers" in text


def test_a_bite_count_that_lags_this_repo_is_reported():
    snapshot = [dict(c) for c in SNAPSHOT]
    snapshot[0]["bitten"] = 6
    snapshot[1]["bitten"] = 1
    assert core.bite_drift(INDEX, snapshot) == [("one-question-two-answers", 6, 2)]
    text = core.report(labelled=[10], snapshot_numbers=set(DEFECTS), closures=[], index=INDEX,
                       pending=PENDING, unclassified=UNCLASSIFIED, snapshot=snapshot, defects=DEFECTS)
    assert "skill says bitten 6, this repo has 2: one-question-two-answers" in text


def test_a_class_with_no_bite_count_is_not_reported_as_drift():
    assert core.bite_drift(INDEX, SNAPSHOT) == []


def test_gh_is_asked_for_closed_defects(monkeypatch):
    seen = []

    def fake(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout='[{"number": 5, "title": "t", "createdAt": "x"}]')
    monkeypatch.setattr(core.subprocess, "run", fake)
    assert core.gh_defects() == {5: {"title": "t", "created": "x"}}
    assert "--label" in seen[0] and "defect" in seen[0] and "closed" in seen[0]


def test_the_commits_here_close_no_unbound_defect():
    log = subprocess.run(["git", "log", "-n", "2000", "--format=%B%x00"], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8")
    if log.returncode != 0:
        pytest.skip(f"no git history here: {log.stderr.strip()}")
    messages = [m for m in log.stdout.split("\x00") if m.strip()]
    defects = core.load_defects()
    assert core.unbound_closures(messages, set(defects), classes.INDEX, classes.PENDING,
                                 classes.UNCLASSIFIED) == []


def test_the_history_of_a_ref_this_clone_lacks_is_none_not_an_error(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert core.git_messages(tmp_path, "origin/main") is None
