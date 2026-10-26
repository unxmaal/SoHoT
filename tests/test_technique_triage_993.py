"""Technique proposals triaged into method crossings; practitioner posts and `soh propose` as sources. #993."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import adopt, cli, delegate, methods, posts, reasons
from harness import memory_store as ms
from harness import technique_triage as tt

ESSAY = "https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/"
FIXTURE = Path(__file__).parent / "fixtures" / "techniques" / "stored_controls_993.json"
REPO = Path(__file__).resolve().parents[1]
INCUMBENTS = {"code": "inc-code", "extract": "inc-ext", "web": "inc-web", "svg": "inc-svg"}

EDGE_CASES = {"mechanism": "prompt", "why": "a pre-prompt that lists edge cases, then answers",
              "name": "Edge Cases First", "note": "list the edge cases, then answer",
              "lanes": ["code", "extract"],
              "steps": [{"as": "cases", "prompt": "List the edge cases of this task. Do not solve it.\n\n{task}"},
                        {"prompt": "{task}\n\nHandle these edge cases:\n{cases}"}]}
KERNEL = {"mechanism": "other", "why": "a fused attention kernel; it changes the runtime, not the prompt"}


def _technique(conn, name, title, url="", description=""):
    ms.record(conn, ms.Seen(name=name, source="hf-daily-papers", url=url, why=title,
                            description=description or title, category=ms.TECHNIQUE))


def _drafter(*answers):
    calls = []

    def draft(row, known=()):
        calls.append(row["name"])
        got = answers[min(len(calls), len(answers)) - 1]
        if isinstance(got, Exception):
            raise got
        return got
    draft.calls = calls
    return draft


def _triage(conn, draft, **kw):
    return tt.triage(conn, draft=draft, incumbent_of=INCUMBENTS.get, **kw)


def _state(conn, name):
    row = conn.execute("SELECT p.state, p.kind, v.tier, v.reason, v.detail FROM proposals p "
                       "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()
    return dict(row) if row else None


def _store_run(conn, run):
    """One stored measure run's paired cells, as evals.run left them."""
    rid = conn.execute("INSERT INTO runs (path, lane, tier, cases_digest, recorded_at) VALUES (?, ?, 'measure', ?, 0)",
                       (f"stored-{run['run']}", run["lane"], run["cases_digest"])).lastrowid
    key = f"{run['method']}/{run['base']}"
    seq = 0
    for case, rep, inc, ch in run["cells"]:
        for cand, passed in ((run["base"], inc), (key, ch)):
            seq += 1
            conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, repeat_index, passed) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (rid, seq, cand, case, rep, int(passed)))
    conn.commit()
    return rid


def _stored(method):
    return next(r for r in json.loads(FIXTURE.read_text(encoding="utf-8"))["runs"] if r["method"] == method)


def _rows(run):
    key = f"{run['method']}/{run['base']}"
    return [{"case_id": c, "candidate": cand, "passed": p, "repeat_index": r, "metrics": {}}
            for c, r, i, ch in run["cells"] for cand, p in ((run["base"], i), (key, ch))]


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


# ---- the acceptance scenarios ------------------------------------------------------------

def test_a_planted_prompt_technique_reaches_a_queued_method_crossing(conn):
    _technique(conn, "arxiv:2610.00001", "Listing edge cases before answering improves LLM replies")
    draft = _drafter(EDGE_CASES)
    (got,) = _triage(conn, draft)
    assert got.outcome == tt.PROMPT and got.method == "t-edge-cases-first"
    for lane, base in (("code", "inc-code"), ("extract", "inc-ext")):
        row = _state(conn, f"t-edge-cases-first:{base}")
        assert row is not None, lane
        assert (row["state"], row["kind"], row["tier"]) == ("queued", methods.CROSSING_KIND, ms.INSPECT)
    assert _state(conn, "t-edge-cases-first:inc-web") is None
    assert draft.calls == ["arxiv:2610.00001"]


def test_a_planted_non_prompt_technique_stays_in_wanted(conn):
    _technique(conn, "arxiv:2610.00002", "A fused attention kernel for faster LLM decoding on GPUs")
    draft = _drafter(KERNEL)
    (got,) = _triage(conn, draft)
    assert got.outcome == tt.OTHER and got.crossings == []
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE kind = ?", (methods.CROSSING_KIND,)).fetchone()[0] == 0
    assert "arxiv:2610.00002" in {r["name"] for r in ms.techniques(conn)}
    assert _triage(conn, draft) == [] and draft.calls == ["arxiv:2610.00002"]


def test_the_essay_maps_to_deepen_without_a_model_call(conn):
    _technique(conn, "post:felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models",
               "How to be more ambitious: a tutorial for humans with models", url=ESSAY)
    draft = _drafter(AssertionError("the drafter was called"))
    (got,) = _triage(conn, draft)
    assert (got.outcome, got.method) == (tt.PROMPT, "deepen") and draft.calls == []
    for base in ("inc-code", "inc-ext", "inc-web"):
        assert _state(conn, f"deepen:{base}")["state"] == "queued"


def test_a_known_useless_technique_is_declined_on_its_stored_evidence(conn):
    stored = _stored("deepen")
    rows = _rows(stored)
    key = f"deepen/{stored['base']}"
    verdict = adopt.decide("extract", adopt._summary(rows, stored["base"]), adopt._summary(rows, key), rows)
    assert adopt.outcome_of(verdict) == ("declined", reasons.CANDIDATE) and "significantly worse" in verdict.why
    run = _store_run(conn, stored)
    assert f"run {run}" in tt.stored_loss(conn, "deepen", "extract")
    _technique(conn, "post:essay", "How to be more ambitious with models", url=ESSAY)
    _triage(conn, _drafter(AssertionError("no call")))
    row = _state(conn, "deepen:inc-ext")
    assert (row["state"], row["tier"], row["reason"]) == ("declined", ms.INSPECT, reasons.CANDIDATE)
    assert "significantly worse" in row["detail"] and f"run {run}" in row["detail"]
    assert _state(conn, "deepen:inc-code")["state"] == "queued"


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/technique_triage.py:stored_loss")
def test_the_newest_stored_run_of_a_method_decides_and_an_older_loss_does_not(conn):
    stored = _stored("deepen")
    _store_run(conn, stored)
    assert "significantly worse" in tt.stored_loss(conn, "deepen", "extract")
    even = {**stored, "run": "rerun", "cells": [[c, r, i, i] for c, r, i, _ in stored["cells"]]}
    _store_run(conn, even)
    assert tt.stored_loss(conn, "deepen", "extract") == ""
    assert tt.stored_loss(conn, "deepen", "code") == "" and tt.stored_loss(conn, "neutral", "extract") == ""


def test_a_run_holding_more_than_one_other_candidate_is_not_read_as_a_pair(conn):
    stored = _stored("deepen")
    rid = _store_run(conn, stored)
    conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed) VALUES (?, 0, 'third', 'x', 1)", (rid,))
    assert tt.stored_loss(conn, "deepen", "extract") == ""


def test_a_known_useful_technique_survives(conn):
    stored = _stored("plan")
    rows = _rows(stored)
    assert adopt._worse(rows, stored["base"], f"plan/{stored['base']}", "code") == ""
    cell, _, _ = adopt.paired_p(rows, stored["base"], f"plan/{stored['base']}", "code")
    assert cell.gained > cell.lost
    _store_run(conn, stored)
    assert tt.stored_loss(conn, "plan", "code") == ""
    _technique(conn, "arxiv:2305.04091", "Plan-and-Solve prompting improves zero-shot reasoning in LLMs")
    (got,) = _triage(conn, _drafter({**EDGE_CASES, "same_as": "plan", "lanes": ["code"]}))
    assert (got.outcome, got.method) == (tt.PROMPT, "plan")
    assert _state(conn, "plan:inc-code")["state"] == "queued"


def test_a_drafted_template_resolves_in_a_fresh_process(conn):
    _technique(conn, "arxiv:2610.00003", "Edge cases first for LLM prompting")
    _triage(conn, _drafter(EDGE_CASES))
    conn.commit()
    probe = ("from harness import methods\n"
             "p = methods.parse('t-edge-cases-first:inc-code')\n"
             "print(p.method.name, p.base, methods.calls('t-edge-cases-first:inc-code'), "
             "methods.is_method('t-edge-cases-first:inc-code'), 'code' in p.method.lanes)\n")
    got = subprocess.run([sys.executable, "-c", probe], cwd=REPO, env=dict(os.environ),
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr
    assert got.stdout.split() == ["t-edge-cases-first", "inc-code", "2", "True", "True"]


# ---- what triage refuses and what it never asks ----------------------------------------------

@pytest.mark.parametrize("answer, said", [
    ({**EDGE_CASES, "steps": [{"prompt": "Answer carefully."}]}, "reads {task}"),
    ({**EDGE_CASES, "steps": [{"prompt": "{task} {nope}"}]}, "reads {nope}"),
    ({**EDGE_CASES, "steps": []}, "at least one step"),
    ({**EDGE_CASES, "lanes": ["image"]}, "no text lane"),
    ({"mechanism": "maybe"}, "mechanism"),
])
def test_a_draft_that_would_not_run_is_refused_and_stays_wanted(conn, answer, said):
    _technique(conn, "arxiv:2610.00004", "A prompting trick for LLM reasoning")
    (got,) = _triage(conn, _drafter(answer))
    assert got.outcome == tt.REFUSED and said in got.why, got.why
    assert got.crossings == [] and "arxiv:2610.00004" in {r["name"] for r in ms.techniques(conn)}


def test_a_reply_that_is_not_json_is_a_refused_draft():
    with pytest.raises(ValueError, match="JSON"):
        tt.parse_draft("I think this is a prompting technique.")
    assert tt.parse_draft('Sure:\n```json\n{"mechanism": "other", "why": "x"}\n```')["mechanism"] == "other"


def test_a_template_no_step_of_which_reads_the_task_is_refused():
    with pytest.raises(ValueError, match="reads {task}"):
        methods.from_template({"name": "x", "steps": [{"prompt": "Be careful."}]})


def test_a_draft_equal_to_a_registered_template_is_that_template(conn):
    neutral = methods.REGISTRY["neutral"].extra["steps"]
    same = {**EDGE_CASES, "name": "library", "steps": [{"prompt": s.prompt} for s in neutral]}
    _technique(conn, "arxiv:2610.00005", "A calming preamble for LLM prompts")
    (got,) = _triage(conn, _drafter(same))
    assert (got.outcome, got.method) == (tt.PROMPT, "neutral")
    assert got.crossings == [] and "negative control" in got.why
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE kind = ?", (methods.CROSSING_KIND,)).fetchone()[0] == 0


def test_two_drafts_with_one_name_get_two_templates(conn):
    _technique(conn, "arxiv:2610.00006", "Edge cases first for LLM prompting")
    _technique(conn, "arxiv:2610.00007", "Edge cases first, again, for LLM prompting")
    other = {**EDGE_CASES, "steps": [{"as": "cases", "prompt": "Name the edge cases.\n{task}"},
                                     {"prompt": "{task}\nEdge cases:\n{cases}"}]}
    got = _triage(conn, _drafter(EDGE_CASES, other))
    assert sorted(g.method for g in got) == ["t-edge-cases-first", "t-edge-cases-first-2"]


def test_triage_asks_the_model_at_most_its_limit_per_run(conn):
    for i in range(5):
        _technique(conn, f"arxiv:2610.0010{i}", f"Prompting trick {i} for LLM reasoning")
    draft = _drafter(KERNEL)
    assert len(_triage(conn, draft, limit=2)) == 2 and len(draft.calls) == 2
    assert len(_triage(conn, draft, limit=2)) == 2 and len(draft.calls) == 4


def test_a_refused_model_call_stops_triage_and_records_nothing(conn):
    _technique(conn, "arxiv:2610.00008", "Prompting trick for LLM reasoning")
    _technique(conn, "arxiv:2610.00009", "Another prompting trick for LLM reasoning")
    draft = _drafter(delegate.Refused("a batch run holds the machine"))
    got = _triage(conn, draft)
    assert got == [] and len(draft.calls) == 1 and "did not answer: a batch run holds" in got.stopped
    assert "stopped at the extract lane's model did not answer" in "\n".join(tt.lines(conn, got))
    assert conn.execute("SELECT COUNT(*) FROM technique_triage").fetchone()[0] == 0


def test_a_draft_cut_at_its_budget_is_refused_and_the_run_goes_on(conn):
    from harness import completion
    _technique(conn, "arxiv:2610.00016", "Prompting trick for LLM reasoning")
    _technique(conn, "arxiv:2610.00017", "Another prompting trick for LLM reasoning")
    cut = completion.CompletionError("cut", reasons.TOKEN_BUDGET_EXHAUSTED)
    draft = _drafter(cut, KERNEL)
    got = _triage(conn, draft)
    assert sorted(g.outcome for g in got) == [tt.OTHER, tt.REFUSED] and not got.stopped
    assert any(f"past {tt.DRAFT_TOKENS} tokens" in g.why for g in got)


def test_a_technique_in_no_text_lane_is_never_drafted(conn):
    _technique(conn, "arxiv:2610.00010", "Faster diffusion image generation with fewer steps")
    _technique(conn, "arxiv:2610.00011", "Continuous batching and KV cache paging for LLM serving")
    draft = _drafter(EDGE_CASES)
    assert _triage(conn, draft) == [] and draft.calls == []


def test_a_parked_lane_or_one_with_no_incumbent_gets_no_crossing(conn, monkeypatch):
    from harness import lanes
    monkeypatch.setattr(lanes, "parked", lambda lane: (lane == "extract", "parked"))
    _technique(conn, "arxiv:2610.00012", "Edge cases first for LLM prompting")
    (got,) = tt.triage(conn, draft=_drafter(EDGE_CASES), incumbent_of={"code": "", "extract": "inc-ext"}.get)
    assert got.outcome == tt.PROMPT and got.crossings == []


def test_the_loop_reports_what_triage_did(conn):
    _technique(conn, "arxiv:2610.00013", "Edge cases first for LLM prompting")
    _technique(conn, "arxiv:2610.00014", "A fused kernel for LLM decoding")
    _technique(conn, "arxiv:2610.00015", "Yet another prompting trick for LLM reasoning")
    got = _triage(conn, _drafter(EDGE_CASES, KERNEL), limit=2)
    text = "\n".join(tt.lines(conn, got))
    assert "=== technique triage ===" in text
    assert "1 prompt, 1 other, 0 refused" in text and "1 still to triage" in text
    assert "queued   code     t-edge-cases-first:inc-code" in text


# ---- sources: practitioner posts and a person's proposal -------------------------------------

def test_names_of_one_technique_agree_across_sources():
    assert tt.key_of("https://arxiv.org/abs/2305.04091v2") == "arxiv:2305.04091"
    assert tt.key_of("https://huggingface.co/papers/2305.04091") == "arxiv:2305.04091"
    assert tt.key_of("arxiv:2305.04091") == "arxiv:2305.04091"
    assert tt.key_of(ESSAY) == tt.key_of("http://www.felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models")
    assert tt.key_of(posts.name_of(ESSAY)) == tt.key_of(ESSAY)
    assert posts.name_of(ESSAY) == "post:felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models"
    assert posts.name_of("https://arxiv.org/abs/2305.04091") == "arxiv:2305.04091"


def test_a_practitioner_feed_entry_is_a_technique_proposal(conn):
    from harness import feeds
    src = feeds.Source("practitioner", "https://posts.invalid/atom", kind=posts.KIND)
    skip = feeds.Source("models", "https://models.invalid/atom", kind="atom")
    entries = [feeds.Entry("Ask for edge cases before code", "https://posts.invalid/edge-cases/",
                           body="<p>A prompt pattern for LLM code generation.</p>")]
    read = []
    got = posts.sweep(conn, sources=[src, skip], reader=lambda s: read.append(s.name) or entries)
    assert read == ["practitioner"] and [s.name for s in got] == ["post:posts.invalid/edge-cases"]
    (row,) = [r for r in ms.techniques(conn) if r["name"] == "post:posts.invalid/edge-cases"]
    assert row["url"] == "https://posts.invalid/edge-cases/" and "prompt pattern" in row["description"]
    assert (ms.source_row(conn, "practitioner") or {}).get("last_status") == "ok"


def test_a_feed_that_fails_is_recorded_failed_and_the_rest_are_read(conn):
    from harness import feeds
    bad = feeds.Source("down", "https://down.invalid/atom", kind=posts.KIND)
    good = feeds.Source("up", "https://up.invalid/atom", kind=posts.KIND)

    def reader(s):
        if s.name == "down":
            raise feeds.FeedError("no network in tests")
        return [feeds.Entry("Critique then revise for LLM answers", "https://up.invalid/a")]
    got = posts.sweep(conn, sources=[bad, good], reader=reader)
    assert [s.name for s in got] == ["post:up.invalid/a"]
    assert ms.source_row(conn, "down")["last_status"] == "failed"


def test_soh_propose_files_a_technique_a_person_names(monkeypatch, capsys):
    monkeypatch.setattr(posts, "fetch_page", lambda url: ("<html><head><title>How to be more ambitious"
                                                           "</title></head><body>Ask four questions.</body></html>"))
    assert cli.main(["propose", ESSAY]) == 0
    assert "post:felixrieseberg.com/how-to-be-more-ambitious" in capsys.readouterr().out
    c = ms.connect()
    try:
        (row,) = [r for r in ms.techniques(c) if r["name"].startswith("post:felixrieseberg.com")]
        assert row["title"] == "How to be more ambitious" and row["url"] == ESSAY
        (got,) = tt.triage(c, draft=_drafter(AssertionError("no call")), incumbent_of=INCUMBENTS.get)
        assert got.method == "deepen"
    finally:
        c.close()


def test_soh_propose_takes_a_title_and_never_fetches(monkeypatch, capsys):
    monkeypatch.setattr(posts, "fetch_page", lambda url: pytest.fail("fetched"))
    assert cli.main(["propose", "https://posts.invalid/x", "--title", "Rubber duck the task first",
                     "--note", "explain the task back before answering"]) == 0
    c = ms.connect()
    try:
        (row,) = [r for r in ms.techniques(c) if r["name"] == "post:posts.invalid/x"]
        assert row["title"] == "Rubber duck the task first" and "explain the task" in row["description"]
    finally:
        c.close()
