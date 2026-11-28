"""The retrieval and agent lanes grown to their holdout targets by generated cases with known-answer controls. #2182."""
import collections
import json
import re
import subprocess
import sys

import pytest
import yaml

from evals import importers
from evals.core import case_digest, load_cases
from evals.importers import agent_synth, retrieval_synth
from harness import adopt, cli, holdout, lexical_rank

RETRIEVAL_DIR = importers.CASES / "retrieval" / "retrieval_synth"
AGENT_DIR = importers.CASES / "agent" / "agent_synth"
#: Live `soh lane-gate status`, 2026-11-27: holdout cases each lane was short of its target.
SHORT = {"retrieval": 228, "agent": 207}
#: Holdout cases in each lane before this import.
BEFORE = {"retrieval": 189, "agent": 125}
POWER = 0.8


def _table_row(capsys, monkeypatch, lane):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert cli.main(["adopt", "--json", "--power", "--lane", lane]) == 0
    return {r["lane"]: r for r in json.loads(capsys.readouterr().out)["lanes"]}[lane]


SHIPPED_RETRIEVAL = load_cases(RETRIEVAL_DIR)
SHIPPED_AGENT = [c for c in load_cases(AGENT_DIR)
                 if int(c.id.rsplit("-", 1)[1]) >= agent_synth.BASE]
RETRIEVAL_ROWS = {f"retrieval-synth-{r['item']:04d}": r for r in retrieval_synth.fetch()}
AGENT_ROWS = {agent_synth.case_id(r): r for r in agent_synth.fetch() if r["item"] >= agent_synth.BASE}


# --- count, holdout and power from the power table ---

@pytest.mark.parametrize("lane", ["retrieval", "agent"])
def test_the_power_table_shows_each_lane_past_its_holdout_target_at_power_point_eight(capsys, monkeypatch, lane):
    row = _table_row(capsys, monkeypatch, lane)
    assert row["holdout"] >= BEFORE[lane] + SHORT[lane], (lane, row["holdout"])
    assert row["power"] >= POWER and row["more_holdout"] == 0, row


def test_the_new_cases_alone_put_enough_holdout_on_each_lane():
    for lane, cases in (("retrieval", SHIPPED_RETRIEVAL), ("agent", SHIPPED_AGENT)):
        side = holdout.for_lane(lane)
        added = sum(1 for c in cases if side.side(c.id) == "holdout")
        assert added >= SHORT[lane], (lane, added)
    assert len(SHIPPED_RETRIEVAL) == retrieval_synth.COUNT
    assert len(SHIPPED_AGENT) == agent_synth.HARD_COUNT


# --- retrieval: the planted wrong ranking and the kinds ---

def test_the_gold_note_first_passes_every_case_and_every_planted_wrong_ranking_fails_every_case():
    got = importers.negative_control(SHIPPED_RETRIEVAL, retrieval_synth.RESPONDERS, retrieval_synth.passes)
    n = len(SHIPPED_RETRIEVAL)
    assert got["reference"] == (n, n)
    assert got["wrong"][0] == 0
    assert got["corpus_order"][0] < n * 0.2 and got["shuffled"][0] < n * 0.2


def test_the_lexical_incumbent_passes_some_of_every_kind_and_neither_all_nor_none():
    by = collections.defaultdict(lambda: [0, 0])
    for r in retrieval_synth.fetch():
        docs = [{"id": d["id"], "text": d["text"]} for d in r["notes"]]
        hit = r["relevant"] in lexical_rank.rank(r["question"], docs)[:retrieval_synth.K]
        for key in (r["kind"], "all"):
            by[key][0] += hit
            by[key][1] += 1
    rate = {k: v[0] / v[1] for k, v in by.items()}
    assert 0.25 < rate["all"] < 0.75, rate
    assert rate["exact"] > rate["synonym"] and 0 < rate["contrast"] < 0.5 and 0 < rate["synonym"] < 0.5, rate


def test_each_question_has_exactly_one_gold_note_and_the_kind_it_claims():
    for row in retrieval_synth.fetch():
        notes = {n["id"]: n for n in row["notes"]}
        gold = notes[row["relevant"]]
        same = [n for n in row["notes"] if (n["system"], n["facet"]) == (gold["system"], gold["facet"])]
        assert same == [gold] and not gold["contrast"], row["item"]
        assert gold["system"] in row["question"] and gold["system"] in gold["text"]
        word = retrieval_synth.FACETS[gold["facet"]][0]
        shared = (retrieval_synth.words(row["question"]) & retrieval_synth.words(gold["text"])) - \
            retrieval_synth.words(gold["system"])
        others = [n for n in row["notes"] if n is not gold and gold["system"] in n["text"]]
        if row["kind"] == "synonym":
            assert not shared, (row["item"], shared)
            assert word not in row["question"].lower()
        else:
            assert retrieval_synth.words(word) <= shared, (row["item"], shared)
        if row["kind"] == "contrast":
            decoy = [n for n in others if n["contrast"] and word in n["text"].lower()]
            assert decoy and all(gold["system"] not in n["system"] for n in decoy), row["item"]


def test_no_two_retrieval_questions_share_a_corpus_and_a_prompt():
    keys = [(r["corpus"], r["question"]) for r in retrieval_synth.fetch()]
    assert len(keys) == len(set(keys))


# --- agent: the hard kinds ---

def test_the_base_cases_are_the_ones_the_generator_drew_before_and_the_hard_kinds_cycle_after_them():
    rows = agent_synth.fetch()
    assert len(rows) == agent_synth.COUNT == agent_synth.BASE + agent_synth.HARD_COUNT
    assert agent_synth.fetch(count=agent_synth.BASE) == rows[:agent_synth.BASE]
    assert {r["kind"] for r in rows[:agent_synth.BASE]} == set(agent_synth.KINDS_BASE)
    hard = collections.Counter(r["kind"] for r in rows[agent_synth.BASE:])
    assert set(hard) == set(agent_synth.HARD) and max(hard.values()) - min(hard.values()) <= 1


def test_a_planted_wrong_answer_fails_every_hard_case_and_the_right_one_passes():
    from evals import sandbox
    for c in SHIPPED_AGENT:
        right, decoys = agent_synth.answers(AGENT_ROWS[c.id])
        assert decoys and right not in decoys, c.id
        assert sandbox.grade(None, None, c.assertions["answer"], f"It is {right}.")["passed"], c.id
        for wrong in decoys + ["I could not tell.", "0"]:
            assert not sandbox.grade(None, None, c.assertions["answer"], f"It is {wrong}.")["passed"], (c.id, wrong)


def test_the_answer_of_a_hard_case_is_what_a_clean_interpreter_computes_from_its_repo():
    for c in SHIPPED_AGENT[::7]:
        row = AGENT_ROWS[c.id]
        check = agent_synth.scene(dict(row))["check"]
        calls = check.get("exprs") or [check["expr"]]
        code = (f"import sys; sys.path.insert(0, '.'); {check['setup'].replace(chr(10), '; ')}; "
                f"print([{', '.join(calls)}][{check.get('pick', -1)}])")
        got = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=c.source.parent / c.params["repo"] / "repo",
                             capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        assert got.stdout.strip() == c.assertions["answer"][0], c.id


def test_a_hard_case_states_its_answer_nowhere_and_asks_for_an_integer():
    stated = 0
    for c in SHIPPED_AGENT:
        repo = c.source.parent / c.params["repo"] / "repo"
        text = "\n".join(p.read_text(encoding="utf-8") for p in repo.rglob("*") if p.is_file())
        assert c.params["tools"] == agent_synth.READ_TOOLS and "integer" in c.prompt
        stated += bool(re.search(rf"(?<![\w.]){c.assertions['answer'][0]}(?![\w.])", text))
    assert stated < len(SHIPPED_AGENT) * 0.15, stated


def test_every_hard_case_is_a_real_run_of_its_repo_with_no_two_alike():
    keys = [(c.prompt, c.params["repo_digest"]) for c in SHIPPED_AGENT]
    assert len(set(keys)) == len(keys)
    sizes = [AGENT_ROWS[c.id] for c in SHIPPED_AGENT if AGENT_ROWS[c.id]["kind"] == "tally"]
    assert len(sizes) >= 150


def test_a_hard_case_whose_wrong_answers_all_equal_the_right_one_is_refused():
    with pytest.raises(agent_synth._Redraw):
        agent_synth._slips(5, 5, 5, 0, -3)


# --- determinism and provenance ---

def test_importing_twice_gives_identical_case_digests(tmp_path):
    digests = []
    for name in ("a", "b"):
        importers.run("retrieval_synth", root=tmp_path / name, rows=retrieval_synth.fetch()[:40])
        importers.run("agent_synth", root=tmp_path / name,
                      rows=agent_synth.fetch()[agent_synth.BASE:agent_synth.BASE + 40])
        digests.append(sorted(case_digest(c) for lane in ("retrieval", "agent") for c in load_cases(tmp_path / name / lane)))
    assert digests[0] == digests[1] and len(digests[0]) == 80


def test_the_shipped_retrieval_cases_are_what_the_generator_writes_now(tmp_path):
    importers.run("retrieval_synth", root=tmp_path)
    fresh = load_cases(tmp_path / "retrieval" / "retrieval_synth")
    assert [case_digest(c) for c in fresh] == [case_digest(c) for c in SHIPPED_RETRIEVAL]


def test_a_different_seed_draws_different_cases_and_the_same_seed_the_same():
    assert retrieval_synth.fetch(seed=1, count=16) == retrieval_synth.fetch(seed=1, count=16)
    assert retrieval_synth.fetch(seed=1, count=16) != retrieval_synth.fetch(seed=2, count=16)
    base = agent_synth.BASE
    assert agent_synth.fetch(seed=1, count=base + 8)[base:] == agent_synth.fetch(seed=1, count=base + 8)[base:]
    assert agent_synth.fetch(seed=1, count=base + 8)[base:] != agent_synth.fetch(seed=2, count=base + 8)[base:]


def test_every_retrieval_case_carries_its_source_license_date_and_a_unique_id():
    assert len({c.id for c in SHIPPED_RETRIEVAL}) == len(SHIPPED_RETRIEVAL)
    assert retrieval_synth.LICENSE in importers.ALLOWED_LICENSES
    for c in SHIPPED_RETRIEVAL:
        att = yaml.safe_load(c.source.read_text(encoding="utf-8"))["attribution"]
        assert att["license"] == "generated" and att["date"] == "2026-11-27"
        assert att["revision"] == retrieval_synth.REVISION and re.fullmatch(r"[0-9a-f]{40}", att["revision"])
