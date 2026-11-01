"""Technique triage measures decoding, multi-call and context templates behind a known-answer canary;
a training paper is final with its reason; the triage limit is a knob that records its cut; the brief says so. #1476."""
from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace

import pytest

from harness import delegate, knobs, methods, reasons
from harness import memory_store as ms
from harness import technique_triage as tt

INCUMBENTS = {"code": "inc-code", "extract": "inc-ext", "web": "inc-web"}
WHERE = SimpleNamespace(model="inc-ext", base="http://gw", sampling={"temperature": 0.2})

MIN_P = {"mechanism": "decoding", "why": "min-p sampling keeps coherent tokens at a high temperature",
         "name": "min p sampling", "lanes": ["code", "extract"],
         "steps": [{"prompt": "{task}", "sampling": {"min_p": 0.1, "temperature": 1.0}}]}
SELF_CONSISTENCY = {"mechanism": "multi-call", "why": "sample several answers and keep the one most agree on",
                    "name": "self consistency", "lanes": ["code", "extract"],
                    "steps": [{"as": "answers", "prompt": "{task}", "samples": 3, "sampling": {"temperature": 0.8}},
                              {"prompt": "{task}\n\nThese replies were drawn:\n{answers}\n\n"
                                         "Reply with the answer most of them agree on."}]}
SANDWICH = {"mechanism": "context", "why": "repeat the question after long material",
            "name": "question after material", "lanes": ["extract"],
            "steps": [{"prompt": "{task}", "context": "sandwich"}]}
DROPS_TASK = {"mechanism": "multi-call", "why": "answer, then polish the answer", "name": "polish the answer",
              "lanes": ["code"], "steps": [{"as": "answer", "prompt": "{task}"},
                                           {"prompt": "Rewrite this more politely: {answer}"}]}
DROPS_MATERIAL = {"mechanism": "context", "why": "answer without the material", "name": "no material",
                  "lanes": ["extract"], "steps": [{"prompt": "{task}", "context": "none"}]}
TRAINING = {"mechanism": "training", "why": "fine-tunes the model with reinforcement learning on traces"}


class Model:
    """The drafting lane's model: it answers a canary task it can read, with the material it was sent."""

    def __init__(self):
        self.sent = []

    def call(self, text, model="", gateway="", modality="", sampling=None, context=""):
        self.sent.append({"text": text, "modality": modality, "sampling": sampling, "context": context})
        whole = f"{context}\n{text}"
        if "17 multiplied by 3" in text:
            answer = "51"
        elif "vault code" in text:
            code = re.search(r"vault code is (\d+)", whole)
            answer = code.group(1) if code else "NOT FOUND"
        else:
            answer = "a polite reply"
        return SimpleNamespace(text=answer)


@pytest.fixture
def model(monkeypatch):
    m = Model()

    def complete(lane, prompt, method=None, context="", **kw):
        assert lane == tt.DRAFT_LANE
        text, cost, _ = delegate.generate("inc-ext", WHERE, lane, prompt, m.call, method=method, context=context)
        return {"text": text, "method": cost, "spec": "inc-ext"}
    monkeypatch.setattr(delegate, "complete", complete)
    return m


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _technique(conn, name, title):
    ms.record(conn, ms.Seen(name=name, source="hf-daily-papers", why=title, description=title,
                            category=ms.TECHNIQUE))


def _drafter(*answers):
    calls = []

    def draft(row, known=()):
        calls.append(row["name"])
        return answers[min(len(calls), len(answers)) - 1]
    draft.calls = calls
    return draft


def _triage(conn, draft, **kw):
    return tt.triage(conn, draft=draft, incumbent_of=INCUMBENTS.get, **kw)


def _state(conn, name):
    row = conn.execute("SELECT p.state, v.tier, v.reason, v.detail, v.until FROM proposals p "
                       "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()
    return dict(row) if row else None


def _stored(conn, method):
    row = conn.execute("SELECT outcome, template FROM technique_triage WHERE method = ?", (method,)).fetchone()
    return row[0], json.loads(row[1]) if row[1] else None


# ---- the acceptance scenarios ------------------------------------------------------------

def test_a_planted_decoding_technique_becomes_a_crossing_whose_template_passes_its_canary(conn, model):
    _technique(conn, "arxiv:2611.00001", "Min-p sampling for creative and coherent LLM outputs")
    (got,) = _triage(conn, _drafter(MIN_P))
    assert (got.outcome, got.method) == (tt.DECODING, "t-min-p-sampling")
    assert {(lane, what) for lane, _, what in got.crossings} == {("code", "queued"), ("extract", "queued")}
    assert _state(conn, "t-min-p-sampling:inc-code")["state"] == "queued"
    outcome, template = _stored(conn, "t-min-p-sampling")
    assert outcome == tt.DECODING and template["kind"] == methods.DECODING_KIND
    # The canary ran every known-answer task with the step's sampling over the lane's own.
    assert len(model.sent) == len(tt.CANARY)
    assert all(s["sampling"] == {"temperature": 1.0, "min_p": 0.1} for s in model.sent)
    assert methods.parse("t-min-p-sampling:inc-code").method.extra["kind"] == methods.DECODING_KIND


def test_a_planted_multi_call_technique_becomes_a_crossing_whose_template_passes_its_canary(conn, model):
    _technique(conn, "arxiv:2611.00002", "Self-consistency improves chain of thought reasoning in LLMs")
    (got,) = _triage(conn, _drafter(SELF_CONSISTENCY))
    assert (got.outcome, got.method) == (tt.MULTI_CALL, "t-self-consistency")
    assert [what for _, _, what in got.crossings] == ["queued", "queued"]
    assert len(model.sent) == 4 * len(tt.CANARY)
    final = [s for s in model.sent if "most of them agree" in s["text"]]
    assert len(final) == len(tt.CANARY) and all("Reply 3:" in s["text"] for s in final)
    assert methods.calls("t-self-consistency:inc-code") == 4


def test_a_planted_context_technique_carries_the_material_through_its_canary(conn, model):
    _technique(conn, "arxiv:2611.00003", "Repeating the question after long context helps LLM reading")
    (got,) = _triage(conn, _drafter(SANDWICH))
    assert got.outcome == tt.CONTEXT and [lane for lane, _, _ in got.crossings] == ["extract"]
    vault = [s for s in model.sent if "vault code" in s["text"]]
    assert vault and vault[0]["context"] == "" and vault[0]["text"].count("vault code in the note") == 2


@pytest.mark.parametrize("draft", [DROPS_TASK, DROPS_MATERIAL], ids=["drops-the-task", "drops-the-material"])
def test_a_template_that_misses_its_canary_is_refused_and_never_crossed(conn, model, draft):
    _technique(conn, "arxiv:2611.00004", "Some LLM prompting trick")
    (got,) = _triage(conn, _drafter(draft))
    assert got.outcome == tt.REFUSED and got.crossings == [] and "known-answer canary" in got.why
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE kind = ?", (methods.CROSSING_KIND,)).fetchone()[0] == 0
    assert _stored(conn, "")[1] is None and methods.drafted("t-" + draft["name"].replace(" ", "-")) is None


def test_a_planted_training_paper_is_final_with_its_reason(conn):
    _technique(conn, "arxiv:2611.00005", "Reinforcement learning fine-tuning for LLM reasoning")
    draft = _drafter(TRAINING)
    (got,) = _triage(conn, draft, canary=lambda m: pytest.fail("a training paper has no template to probe"))
    assert got.outcome == tt.TRAINING and got.crossings == []
    st = _state(conn, "arxiv:2611.00005")
    assert (st["state"], st["tier"], st["reason"], st["until"]) == ("declined", ms.INSPECT, reasons.CANDIDATE, "")
    assert "needs training or new weights" in st["detail"] and "reinforcement learning" in st["detail"]
    assert "arxiv:2611.00005" not in {r["name"] for r in ms.techniques(conn)}
    assert _triage(conn, draft) == [] and draft.calls == ["arxiv:2611.00005"]


def test_the_triage_limit_is_a_registered_knob_that_records_a_cut_when_it_binds(conn):
    k = knobs.KNOBS["triage_per_run"]
    assert "harness/technique_triage.py:PER_RUN" in k.sites and k.default() == tt.PER_RUN
    for i in range(3):
        _technique(conn, f"arxiv:2611.0001{i}", f"An LLM benchmark number {i}")
    draft = _drafter({"mechanism": "other", "why": "a benchmark"})
    got = _triage(conn, draft, limit=2)
    assert len(got) == 2 and got.stopped == "the limit of 2 draft(s) this run"
    cut = conn.execute("SELECT knob, value, what FROM limit_cuts WHERE knob = 'triage_per_run'").fetchall()
    waiting = ({f"arxiv:2611.0001{i}" for i in range(3)} - set(draft.calls)).pop()
    assert [(c[0], c[1]) for c in cut] == [("triage_per_run", 2.0)] and f"{waiting} and later wait" in cut[0][2]


def test_the_limit_is_read_when_triage_runs_so_a_knob_sweep_reaches_it(conn, monkeypatch):
    for i in range(2):
        _technique(conn, f"arxiv:2611.0002{i}", f"An LLM benchmark number {i}")
    monkeypatch.setattr(tt, "PER_RUN", 1)
    got = _triage(conn, _drafter({"mechanism": "other", "why": "a benchmark"}))
    assert len(got) == 1 and "limit of 1" in got.stopped


def test_the_morning_brief_lists_measured_won_lost_and_unmeasurable_by_reason(conn, model):
    from harness import morning
    from harness.commands.morning import render
    _technique(conn, "arxiv:2611.00030", "Min-p sampling for LLM outputs")
    _technique(conn, "arxiv:2611.00031", "RL fine-tuning for LLM reasoning")
    _technique(conn, "arxiv:2611.00032", "A paged KV cache for LLM serving")
    _triage(conn, _drafter(MIN_P, TRAINING, {"mechanism": "engine", "why": "a serving cache"}))
    ms.decide(conn, "t-min-p-sampling:inc-code", "declined", tier=ms.MEASURE, reason=reasons.CANDIDATE,
              detail="lost the paired measure")
    t = morning.techniques(conn, since=0.0)
    assert t["crossings"] == {"measured": 1, "won": 0, "lost": 1, "declined": 0, "waiting": 1}
    assert t["all"][tt.TRAINING] == 1 and t["all"][tt.ENGINE] == 1 and t["triaged"][tt.DECODING] == 1
    r = morning.gather(conn, 1.0, 0.0, gh=lambda argv: "", git=lambda argv: "", lanes=lambda c: [],
                       stalls=lambda c: [])
    text = "\n".join(render(r))
    assert "techniques 3 triaged: 0 prompt, 1 decoding" in text
    assert "crossings: 1 measured (0 won, 1 lost)" in text
    assert "1 training (needs training" in text and "1 engine (an engine or serving change" in text


def test_a_row_triaged_as_other_before_the_wider_classes_is_triaged_again(conn, model):
    _technique(conn, "arxiv:2611.00040", "Self-consistency for LLM reasoning")
    pid = conn.execute("SELECT id FROM proposals WHERE name = 'arxiv:2611.00040'").fetchone()[0]
    conn.execute("INSERT INTO technique_triage (proposal_id, outcome, method, why, template, drafted_by, triaged_at) "
                 "VALUES (?, 'other', '', 'involves multiple steps beyond just changing the prompt', '', '', 0)",
                 (pid,))
    conn.commit()
    (got,) = _triage(conn, _drafter(SELF_CONSISTENCY))
    assert got.outcome == tt.MULTI_CALL
    rows = conn.execute("SELECT outcome FROM technique_triage WHERE proposal_id = ?", (pid,)).fetchall()
    assert [r[0] for r in rows] == [tt.MULTI_CALL]


def test_an_unrouted_technique_is_drafted_and_one_in_another_lane_is_not(conn):
    _technique(conn, "arxiv:2611.00050", "Protein folding from sequence alignments")
    _technique(conn, "arxiv:2611.00051", "Faster diffusion image generation with fewer steps")
    draft = _drafter({"mechanism": "other", "why": "biology"})
    (got,) = _triage(conn, draft)
    assert draft.calls == ["arxiv:2611.00050"] and got.outcome == tt.NOT_A_METHOD


# ---- templates: decoding, samples and context shapes --------------------------------------

def test_a_default_template_digests_as_it_did_before_the_new_fields():
    deepen = methods.REGISTRY["deepen"]
    old = json.dumps([[s.prompt, s.name, s.answers] for s in deepen.extra["steps"]])
    assert deepen.extra["digest"] == hashlib.sha256(old.encode("utf-8")).hexdigest()[:12]
    plain = methods.from_template({"name": "x", "steps": [{"prompt": "{task}"}]})
    tuned = methods.from_template({"name": "x", "steps": [{"prompt": "{task}", "sampling": {"min_p": 0.1}}]})
    assert plain.extra["digest"] != tuned.extra["digest"]


@pytest.mark.parametrize("step, last, says", [
    ({"prompt": "{task}", "sampling": {"mirostat": 2}}, True, "mirostat"),
    ({"prompt": "{task}", "sampling": {"temperature": 9}}, True, "not a number from"),
    ({"prompt": "{task}", "sampling": {"top_p": True}}, True, "not a number from"),
    ({"prompt": "{task}", "samples": 3}, True, "cannot draw 3 samples"),
    ({"as": "a", "prompt": "{task}", "samples": 99}, False, "from 1 to"),
    ({"prompt": "{task}", "context": "sideways"}, True, "sideways"),
])
def test_a_template_step_outside_what_a_server_accepts_is_refused(step, last, says):
    steps = [step] if last else [step, {"prompt": "{a}"}]
    with pytest.raises(ValueError, match=says):
        methods.from_template({"name": "x", "steps": steps})


@pytest.mark.parametrize("kind", [methods.DECODING_KIND, methods.MULTI_CALL_KIND, methods.CONTEXT_KIND])
def test_a_kind_the_steps_do_not_show_is_refused(kind):
    with pytest.raises(ValueError, match=f"a {kind} template"):
        methods.from_template({"name": "x", "kind": kind, "steps": [{"prompt": "{task}"}]})
    with pytest.raises(ValueError, match="kind 'magic'"):
        methods.from_template({"name": "x", "kind": "magic", "steps": [{"prompt": "{task}"}]})


@pytest.mark.parametrize("how, prompt, context", [
    ("before", "Q", "M"), ("none", "Q", ""), ("after", "Q\n\n---\n\nM", ""),
    ("sandwich", "Q\n\n---\n\nM\n\n---\n\nQ", ""), ("numbered", "Q", "    1  M"),
])
def test_each_context_shape_puts_the_material_where_it_says(how, prompt, context):
    assert methods.shape("Q", "M", how) == (prompt, context)
    assert methods.shape("Q", "", how) == ("Q", "")


def test_the_eval_runner_sends_each_steps_sampling_samples_and_shape(monkeypatch):
    from evals.core import Case
    from evals.runners.method import TemplateRunner
    from evals.runners.text import CompletionRunner
    from harness import completion
    asked = []

    def fake(prompt, model, gateway="", **kw):
        asked.append((prompt, kw.get("context"), kw.get("sampling")))
        return f"draft {len(asked)}", {"completion_tokens": 3}
    monkeypatch.setattr(completion, "complete_with_usage", fake)
    base = CompletionRunner("http://gw", "q3-4b", sampling={"temperature": 0.2})
    answered = []

    class Answer(CompletionRunner):
        def generate(self, case):
            answered.append((case.prompt, case.context, self.sampling))
            return "51", 0
    base.__class__ = Answer
    m = methods.from_template({"name": "x", "kind": "multi-call", "steps": [
        {"as": "drafts", "prompt": "{task}", "samples": 2, "sampling": {"temperature": 0.9}, "context": "numbered"},
        {"prompt": "{task}\n{drafts}", "sampling": {"min_p": 0.05}, "context": "after"}]})
    r = TemplateRunner(base, m).run(Case(id="c", modality="extract", prompt="Q?", context="line one",
                                         assertions={"equals": "51"}))
    assert r.passed and r.metrics["method_calls"] == 3
    assert [a[1] for a in asked] == ["    1  line one"] * 2
    assert all(a[2]["temperature"] == 0.9 for a in asked)
    (prompt, context, sampling), = answered
    assert context == "" and prompt.endswith("line one") and "Reply 2:\ndraft 2" in prompt
    assert sampling == {"temperature": 0.2, "min_p": 0.05} and base.sampling == {"temperature": 0.2}
