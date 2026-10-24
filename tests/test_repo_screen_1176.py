"""The repo screen draws a fixed, stratified subset and judges pooled screen draws by tasks against the base. #1176."""
from __future__ import annotations

import json
import random
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import repo_screen as S
from evals.core import load_cases
from evals.importers import CASES
from harness import knobs

REPO = CASES / "repo"
#: The default subset over the committed cases and anchors; a change here changes which screens compare.
DEFAULT = ["infovore-252-spec", "infovore-327-spec", "infovore-348-spec", "infovore-349-symptom",
           "infovore-353-spec", "mcm-engine-142-spec", "mcm-engine-145-spec", "mcm-engine-170-symptom",
           "mcm-engine-182-spec", "mcm-engine-27-spec", "mcm-engine-63-spec", "mcm-engine-80-symptom",
           "mcm-engine-pr162-request", "sohot-318-omnisvg-spelling", "sohot-374-spec", "sohot-396-spec",
           "sohot-438-symptom", "sohot-570-spec", "sohot-598-symptom", "sohot-788-spec", "sohot-858-symptom",
           "sohot-859-symptom", "sohot-pr1101-request", "sohot-pr883-request"]


def _case(cid, group, variant, fix=None):
    return SimpleNamespace(id=cid, modality="repo", source=Path(f"/c/{group}/{cid}.yaml"),
                           params={"fix": fix or f"fix-{cid}", "variant": variant})


def _suite():
    """Six strata of uneven size, spec and symptom of one task sharing a fix."""
    out = []
    for g, n in (("history", 12), ("history_infovore", 7), ("transcripts", 5)):
        for i in range(n):
            out.append(_case(f"{g}-{i}-spec", g, "spec", f"{g}{i}") if g != "transcripts"
                       else _case(f"{g}-{i}-request", g, "request"))
            if g != "transcripts" and i % 2 == 0:
                out.append(_case(f"{g}-{i}-symptom", g, "symptom", f"{g}{i}"))
    return out


@pytest.fixture(scope="module")
def repo_cases():
    return load_cases(REPO)


def test_every_stratum_of_the_committed_exam_is_in_the_default_subset(repo_cases):
    chosen = S.pick(repo_cases)
    groups = {p.name for p in REPO.iterdir() if p.is_dir() and any(p.rglob("*.yaml"))}
    assert groups == {"history", "history_infovore", "history_mcm_engine", "transcripts"}
    assert groups | {"repo"} == {S.group_of(c) for c in chosen}
    assert {S.stratum_of(c) for c in repo_cases} == {S.stratum_of(c) for c in chosen}
    assert len(chosen) == S.CASES


def test_an_unstratified_draw_of_the_same_size_misses_a_stratum(repo_cases):
    # Negative control: the coverage test above can fail, because a draw without strata does miss some.
    ids = sorted(repo_cases, key=lambda c: S._hash(c.id))[:S.CASES]
    assert {S.stratum_of(c) for c in repo_cases} - {S.stratum_of(c) for c in ids}


def test_the_default_subset_is_pinned_and_shows_both_anchor_ends(repo_cases):
    chosen = S.pick(repo_cases)
    assert [c.id for c in chosen] == DEFAULT
    anchors = S.load_anchors()
    classes = {S.class_of(c.id, anchors) for c in chosen}
    assert {"base_pass", "neither", "reference_only"} <= classes
    assert len({S.task_key(c) for c in chosen}) == len(chosen)


def test_the_draw_is_the_same_whatever_order_the_cases_arrive_in():
    cases = _suite()
    first = [c.id for c in S.pick(cases, 10, {})]
    for seed in range(5):
        random.Random(seed).shuffle(cases)
        assert [c.id for c in S.pick(cases, 10, {})] == first


def test_each_stratum_gets_one_then_its_share_of_the_rest():
    got = S.allocate({("a", "spec"): 30, ("a", "symptom"): 10, ("b", "spec"): 1}, 12)
    assert got == {("a", "spec"): 8, ("a", "symptom"): 3, ("b", "spec"): 1}
    assert sum(S.allocate({("a", "x"): 19, ("b", "y"): 4, ("c", "z"): 26}, 24).values()) == 24
    assert S.allocate({("a", "x"): 3, ("b", "y"): 2}, 99) == {("a", "x"): 3, ("b", "y"): 2}


def test_too_few_cases_for_the_strata_is_refused():
    with pytest.raises(S.Refused, match="cannot cover"):
        S.pick(_suite(), 3, {})


def test_within_a_stratum_the_draw_follows_the_anchor_classes():
    cases = [_case(f"h-{i}-spec", "history", "spec") for i in range(20)]
    base = {c.id: i < 4 for i, c in enumerate(cases)}
    ref = {c.id: i < 14 for i, c in enumerate(cases)}
    anchors = {"base": {"passed": base}, "reference": {"passed": ref}}
    chosen = S.pick(cases, 10, anchors)
    got = sorted(S.class_of(c.id, anchors) for c in chosen)
    assert got.count("base_pass") == 2 and got.count("reference_only") == 5 and got.count("neither") == 3


def test_a_task_already_drawn_is_skipped_for_another_of_its_class():
    cases = []
    for i in range(6):
        cases += [_case(f"t{i}-spec", "history", "spec", f"t{i}"), _case(f"t{i}-symptom", "history", "symptom", f"t{i}")]
    chosen = S.pick(cases, 6, {})
    assert len({S.task_key(c) for c in chosen}) == 6


def test_the_subset_size_is_a_registered_knob_the_draw_reads_when_it_runs():
    for name, value in (("repo_screen_cases", 24), ("screen_outside_votes", 3), ("screen_repeats", 3)):
        k = knobs.KNOBS[name]
        assert k.default() == value and value in k.values and k.note
    with knobs.rebind({"repo_screen_cases": 12}):
        assert len(S.pick(_suite(), anchors={})) == 12


def _rows(cand, outcomes, *, run=2, draws=1):
    """outcomes: case id -> list of pass bits, one per draw."""
    return [{"run_id": run, "candidate": cand, "case_id": cid if d == 0 else f"{cid}#{d + 1}", "repeat_index": d + 1,
             "passed": bits[d], "seconds": 10.0, "metrics": {"tokens_per_s": 30.0}}
            for cid, bits in outcomes.items() for d in range(min(draws, len(bits)))]


CASES4 = [_case(f"k{i}-spec", "history", "spec") for i in range(4)]


def _verdict(base_bits, cand_bits, draws=1, votes=0):
    base = _rows("base", {c.id: [b] for c, b in zip(CASES4, base_bits)}, run=1)
    cand = _rows("cand", {c.id: b for c, b in zip(CASES4, cand_bits)}, draws=draws)
    return S.verdict(base, cand, CASES4, outside_votes=votes)


def test_a_candidate_that_wins_more_tasks_than_it_loses_survives():
    v = _verdict([1, 0, 0, 0], [[1], [1], [1], [0]])
    assert (v["verdict"], v["task_wins"], v["task_losses"]) == ("survives", 2, 0)


def test_a_failed_screen_without_outside_votes_is_declined():
    v = _verdict([1, 1, 0, 0], [[0], [0], [1], [0]], votes=2)
    assert v["verdict"] == "declined" and "finding" not in v["why"]


def test_a_failed_screen_the_outside_votes_disagree_with_reruns_before_any_decline():
    v = _verdict([1, 1, 0, 0], [[0], [0], [1], [0]], votes=3)
    assert v["verdict"] == "rerun" and "--repeat 3" in v["why"]


def test_after_the_repeats_a_candidate_still_below_is_declined_and_the_exam_questioned():
    v = _verdict([1, 1, 0, 0], [[0, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]], draws=4, votes=3)
    assert v["draws"] == 4 and v["verdict"] == "declined" and "finding about the exam" in v["why"]


def test_after_the_repeats_a_tie_is_not_below_the_base():
    v = _verdict([1, 0, 0, 0], [[1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], draws=4, votes=3)
    assert v["verdict"] == "survives"
    assert _verdict([1, 0, 0, 0], [[1], [0], [0], [0]])["verdict"] == "declined"


def test_the_verdict_refuses_rows_it_cannot_pair():
    base = _rows("base", {CASES4[0].id: [1]}, run=1)
    with pytest.raises(S.Refused, match="no row"):
        S.verdict(base, _rows("cand", {CASES4[1].id: [1]}), CASES4)
    two = _rows("a", {CASES4[0].id: [1]}) + _rows("b", {CASES4[0].id: [1]})
    with pytest.raises(S.Refused, match="one candidate"):
        S.verdict(base, two, CASES4)


def _store(path, cases, chosen):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (id INTEGER, lane TEXT, repeat_count INTEGER, cases_digest TEXT, receipt TEXT, "
                 "environment TEXT, generated_at REAL)")
    conn.execute("CREATE TABLE results (run_id INTEGER, seq INTEGER, candidate TEXT, case_id TEXT, repeat_index "
                 "INTEGER, passed INTEGER, failure_class TEXT, hit_limit TEXT, seconds REAL, metrics TEXT)")
    for rid, cand, ids in ((1, "base", [c.id for c in cases]), (2, "cand", [c.id for c in chosen]),
                           (3, "cand", [c.id for c in chosen[:-1]])):
        conn.execute("INSERT INTO runs VALUES (?, 'repo', 1, 'd', ?, '{}', 0)",
                     (rid, json.dumps({"modality": "repo", "case_ids": ids})))
        for i, cid in enumerate(ids):
            conn.execute("INSERT INTO results VALUES (?, ?, ?, ?, 1, ?, '', '', 5.0, '{}')",
                         (rid, i, cand, cid, int(rid == 2)))
    conn.commit()
    conn.close()


def test_the_command_judges_a_stored_screen_and_refuses_one_of_another_subset(repo_cases, tmp_path, capsys):
    from harness.commands import repo_screen as cmd
    chosen = S.pick(repo_cases)
    store = tmp_path / "store.db"
    _store(store, repo_cases, chosen)

    def run(*runs):
        a = SimpleNamespace(action="verdict", runs=list(runs), base=1, outside_votes=0, n=0, write=False,
                            anchors="", store=str(store), cases="")
        return cmd.cmd_repo_screen(a)

    assert run(2) == 0
    assert "SURVIVES" in capsys.readouterr().out
    assert run(3) == 1
    assert "did not run the current screen subset" in capsys.readouterr().err


def test_evals_run_cuts_a_repo_run_to_the_subset_and_refuses_other_lanes(repo_cases):
    from evals import run as R
    got = R.screen_subset(list(repo_cases), SimpleNamespace(repo_screen=True, modality="repo"))
    assert [c.id for c in got] == DEFAULT
    assert R.screen_subset(list(repo_cases), SimpleNamespace(repo_screen=False, modality="repo")) == list(repo_cases)
    with pytest.raises(SystemExit, match="--modality repo"):
        R.screen_subset([], SimpleNamespace(repo_screen=True, modality="code"))
    assert R.parse_args(["--modality", "repo", "--repo-screen"]).repo_screen
