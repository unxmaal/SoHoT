"""The decide lane: typed decisions, accuracy and calibration. #423."""
import json
import random
import re
from pathlib import Path

import pytest

from evals import core, run
from evals.core import Case, load_cases, score, summarize
from harness import completion, engines, lanes, screen
from harness.checks import decide

ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "evals" / "cases" / "decide")


def _schema(case):
    return case.params["schema"]


def _gold(case):
    return case.assertions["answers"]


# --- the cases --------------------------------------------------------------

def test_the_lane_has_enough_cases_with_several_fields_each():
    assert len(CASES) >= 20
    assert all(len(_schema(c)) >= 4 for c in CASES)
    assert {c.id.split("-")[0] for c in CASES} == {"route", "check", "policy", "rate"}


def test_every_case_names_its_source_license_and_pinned_selection():
    import yaml
    from evals import decide_corpus as dc
    allowed = {s["license"] for s in dc.SOURCES.values()}
    for c in CASES:
        raw = yaml.safe_load(c.source.read_text(encoding="utf-8"))
        a = raw["attribution"]
        assert a["license"] in allowed and a["url"].startswith("https://")
        assert f"@{dc.NIMBLE_REV}:" in a["selected_from"]


def test_the_corpus_pin_is_the_engine_pin():
    from evals import decide_corpus as dc
    pins = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    assert f'NIMBLE_REV="{dc.NIMBLE_REV}"' in pins


def test_no_boolean_field_family_is_answered_by_one_constant():
    """A field whose gold never varies across its family is passed by a constant."""
    by: dict = {}
    for c in CASES:
        for name, spec in _schema(c).items():
            if spec["type"] == "boolean" and not name.startswith("q"):
                by.setdefault((c.id.split("-")[0], name), set()).add(_gold(c)[name])
    varied = [k for k, v in by.items() if len(v) == 2]
    assert len(varied) >= 6, by


def test_the_rendered_prompt_names_every_field_and_its_codes():
    c = next(c for c in CASES if c.id.startswith("route-"))
    for name in _schema(c):
        assert f"{name}:" in c.prompt
    assert "A = alarm" in c.prompt and "A = false" in c.prompt and "B = true" in c.prompt


def test_a_case_with_a_gold_answer_outside_its_choices_is_refused(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "id: x\nmodality: decide\nprompt: p\ncontext: c\n"
        "params: {schema: {f: {type: enum, choices: [a, b], description: d}}}\n"
        "assert: {answers: {f: c}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not one of"):
        load_cases(tmp_path)


# --- the metric and its negative control (gauntlet rule 1) -------------------

def perfect(case):
    return json.dumps({"answers": {k: decide.key(v) for k, v in _gold(case).items()},
                       "probabilities": {k: {decide.key(v): 1.0}
                                         for k, v in _gold(case).items()}})


def randomly(case, rng):
    """A known-random responder: a random distribution per field, answer its argmax."""
    probs = {}
    for name, spec in _schema(case).items():
        weights = [rng.random() for _ in decide.choices(spec)]
        probs[name] = dict(zip(decide.code_map(spec).values(), weights))
    return json.dumps({"probabilities": probs})


def first_choice(case):
    return json.dumps({n: "A" for n in _schema(case)})


def _summary(artifact_of):
    rows = []
    for c in CASES:
        r = score(c, artifact_of(c))
        r.candidate = "x"
        rows.append(r)
    return summarize(rows)["x"]


def test_a_perfect_and_a_random_responder_separate():
    rng = random.Random(423)
    good = _summary(perfect)
    bad = _summary(lambda c: randomly(c, rng))
    assert good["metrics"]["decide_accuracy"] == 1.0
    assert good["metrics"]["decide_brier"] == 0.0
    assert good["metrics"]["decide_ece"] == 0.0
    assert good["pass_rate"] == 1.0
    assert bad["metrics"]["decide_accuracy"] < 0.6
    assert bad["metrics"]["decide_brier"] > 0.5
    assert bad["metrics"]["decide_ece"] > 0.1
    assert bad["pass_rate"] < 0.2


def test_a_constant_responder_is_far_from_perfect():
    got = _summary(first_choice)
    assert got["metrics"]["decide_accuracy"] < 0.7
    assert got["metrics"]["calibrated"] == 0.0
    assert got["pass_rate"] < 0.2


def test_answers_without_probabilities_score_one_hot_and_uncalibrated():
    c = CASES[0]
    gold = {k: decide.key(v) for k, v in _gold(c).items()}
    r = score(c, json.dumps(gold))
    assert r.passed and r.metrics["decide_brier"] == 0.0
    assert r.metrics["calibrated"] == 0.0
    wrong_field, spec = next(iter(_schema(c).items()))
    other = next(v for v in decide.code_map(spec).values() if v != gold[wrong_field])
    r = score(c, json.dumps({**gold, wrong_field: other}))
    assert not r.passed and wrong_field in r.detail
    assert r.metrics["decide_brier_sum"] == 2.0


def test_a_missing_field_is_wrong_and_scores_the_zero_vector():
    spec = {"f": {"type": "boolean", "description": "d"}}
    r = decide.check("{}", spec, {"f": True})
    assert not r.ok and "no answer for f" in r.reason
    assert r.metrics["decide_brier_sum"] == 1.0


def test_brier_is_the_multiclass_sum():
    spec = {"f": {"type": "enum", "choices": ["a", "b", "c"], "description": "d"}}
    r = decide.check(json.dumps({"probabilities": {"f": {"a": 0.5, "b": 0.3, "c": 0.2}}}),
                     spec, {"f": "a"})
    assert r.metrics["decide_brier_sum"] == pytest.approx(0.25 + 0.09 + 0.04)
    assert r.metrics["calibrated"] == 1.0


def test_ece_matches_a_hand_computed_value():
    pairs = [(0.95, True), (0.95, False), (0.55, True), (0.55, True)]
    assert decide.ece(pairs) == pytest.approx(0.5 * 0.45 + 0.5 * 0.45)
    assert decide.ece([(1.0, True)] * 3) == 0.0


def test_ece_is_withheld_below_the_bin_floor():
    rows = []
    for c in CASES[:3]:
        r = score(c, perfect(c))
        r.candidate = "x"
        rows.append(r)
    assert "decide_ece" not in summarize(rows)["x"]["metrics"]


def test_accuracy_pools_fields_rather_than_averaging_cases():
    a = core.Result("a", "x", True, 0, 0, "", metrics={
        "decide_accuracy": 1.0, "decide_correct": 1, "decide_fields": 1,
        "decide_brier": 0.0, "decide_brier_sum": 0.0})
    b = core.Result("b", "x", False, 0, 0, "w", metrics={
        "decide_accuracy": 0.0, "decide_correct": 0, "decide_fields": 9,
        "decide_brier": 2.0, "decide_brier_sum": 18.0})
    got = summarize([a, b])["x"]["metrics"]
    assert got["decide_accuracy"] == 0.1
    assert got["decide_brier"] == 1.8


def test_the_stored_summary_keeps_the_calibration():
    """runs.summarize rebuilds from stored metrics; the decisions must survive it."""
    from harness import runs
    rows = []
    for c in CASES:
        r = score(c, perfect(c))
        r.candidate = "x"
        rows.append(json.loads(json.dumps(vars(r), default=str)))
    assert runs.summarize(rows)["x"]["metrics"]["decide_ece"] == 0.0


# --- parsing what models write ------------------------------------------------

SPEC = {"route": {"type": "enum", "choices": ["billing", "tech"], "description": "d"},
        "urgent": {"type": "boolean", "description": "d"}}


@pytest.mark.parametrize("text,want", [
    ('{"route": "B", "urgent": "A"}', ("tech", "false")),
    ('```json\n{"route": "billing", "urgent": true}\n```', ("billing", "true")),
    ('Sure. {"route": "b", "urgent": "yes"}', ("tech", "true")),
    ('{"route": "Z", "urgent": "maybe"}', (None, None)),
])
def test_parse_reads_codes_values_and_fences(text, want):
    got = decide.parse(text, SPEC)
    assert (got["route"]["answer"], got["urgent"]["answer"]) == want


def _tok(text, lp, top=()):
    return {"token": text, "logprob": lp,
            "top_logprobs": [{"token": t, "logprob": p} for t, p in top]}


def test_logprobs_become_a_distribution_per_field():
    import math
    tokens = [_tok("{\"", 0), _tok("route", 0), _tok("\":", 0), _tok("Ġ\"", 0),
              _tok("B", math.log(0.7), [("B", math.log(0.7)), ("A", math.log(0.2)),
                                        ("Ġthe", math.log(0.1))]),
              _tok("\",", 0), _tok("urgent", 0), _tok("\":\"", 0),
              _tok("A", math.log(0.9), [("A", math.log(0.9)), ("B", math.log(0.1))]),
              _tok("\"}", 0)]
    got = decide.from_logprobs('{"route": "B", "urgent": "A"}', tokens, SPEC)
    assert got["answers"] == {"route": "tech", "urgent": "false"}
    assert got["probabilities"]["route"] == pytest.approx({"tech": 0.7, "billing": 0.2})
    parsed = decide.parse(json.dumps(got), SPEC)
    assert parsed["route"]["probs"]["tech"] == pytest.approx(0.7 / 0.9)


def test_a_letter_that_does_not_line_up_falls_back_to_one_hot():
    tokens = [_tok("{", 0), _tok("C", -0.1, [("C", -0.1)]), _tok("A", -0.1, [("A", -0.1)])]
    got = decide.from_logprobs('{"route": "B", "urgent": "A"}', tokens, SPEC)
    assert got["answers"]["route"] == "tech" and "route" not in got["probabilities"]


# --- runners ------------------------------------------------------------------

def test_the_completion_asks_for_logprobs_only_when_told(monkeypatch):
    seen = []

    class R:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "{}"},
                                 "logprobs": {"content": [_tok("{", 0)]}}]}

    monkeypatch.setattr(completion, "_post", lambda g, p, t: seen.append(p) or R())
    _, _, tokens = completion.complete_with_logprobs("x", "m", top_logprobs=5)
    assert seen[-1]["logprobs"] is True and seen[-1]["top_logprobs"] == 5
    assert tokens and tokens[0]["token"] == "{"
    completion.complete_with_usage("x", "m")
    assert "logprobs" not in seen[-1]


def test_the_text_runner_writes_probabilities_when_the_server_has_them(monkeypatch):
    import math

    from evals.runners.text import CompletionRunner
    c = Case(id="d", modality="decide", prompt="p", params={"schema": SPEC},
             assertions={"answers": {"route": "tech", "urgent": False}})
    text = '{"route": "B", "urgent": "A"}'
    tokens = [_tok("{", 0), _tok("B", math.log(0.8), [("B", math.log(0.8)), ("A", math.log(0.2))]),
              _tok("A", math.log(0.6), [("A", math.log(0.6)), ("B", math.log(0.4))])]
    monkeypatch.setattr(completion, "complete_full",
                        lambda *a, **k: completion.Completion(text, {}, tokens))
    r = CompletionRunner("http://gw", "q3-4b").run(c)
    assert r.passed and r.metrics["calibrated"] == 1.0
    assert r.metrics["decide_brier_sum"] == pytest.approx(2 * 0.2 ** 2 + 2 * 0.4 ** 2)
    monkeypatch.setattr(completion, "complete_full",
                        lambda *a, **k: completion.Completion(text, {}, []))
    r = CompletionRunner("http://gw", "q3-4b").run(c)
    assert r.passed and r.metrics["calibrated"] == 0.0


def test_claude_code_is_a_baseline_with_answers_only():
    from evals.runners.claude_code import ClaudeCodeRunner

    class Proc:
        returncode, stderr = 0, ""
        stdout = json.dumps({"result": '{"route": "B", "urgent": "A"}'})

    seen = {}
    c = Case(id="d", modality="decide", prompt="p", params={"schema": SPEC},
             assertions={"answers": {"route": "tech", "urgent": False}})
    r = ClaudeCodeRunner("claude-opus-5-5",
                         execute=lambda argv, **kw: seen.update(argv=argv) or Proc()).run(c)
    assert r.passed and r.metrics["calibrated"] == 0.0
    assert seen["argv"][seen["argv"].index("--system-prompt") + 1] == completion.SYSTEM["decide"]
    assert "decide" in run.TEXT_MODALITIES
    assert run.cases_for("claude-code:claude-opus-5-5", [c]) == [c]


# --- the nimble engine ---------------------------------------------------------

NIMBLE = "bespokelabs/Bespoke-Nimble-9B"


def test_nimble_is_a_decide_engine_that_loads_adapters():
    eng = engines.resolve(f"nimble:{NIMBLE}")
    assert (eng.modality, eng.output_suffix, eng.name) == ("decide", ".json",
                                                           "nimble/Bespoke-Nimble-9B")
    assert engines.loads_adapters(f"nimble:{NIMBLE}")
    assert not engines.loads_adapters("diffusers:org/x")
    assert run.kind_of(f"nimble:{NIMBLE}") == "process"
    assert run.modality_of(f"nimble:{NIMBLE}") == "decide"


def test_nimble_passes_the_context_and_schema_through_argv(monkeypatch, tmp_path):
    monkeypatch.setenv("NIMBLE_BIN", str(tmp_path / "nimble-score.sh"))
    eng = engines.resolve(f"nimble:{NIMBLE},revision=abc")
    a = eng.argv("prompt", tmp_path / "o.json", {"schema": SPEC, "context": "ctx"})
    assert a[0] == str(tmp_path / "nimble-score.sh")
    assert a[a.index("--context") + 1] == "ctx"
    assert json.loads(a[a.index("--schema") + 1]) == SPEC
    assert a[a.index("--revision") + 1] == "abc"
    with pytest.raises(ValueError, match="no schema"):
        eng.argv("p", tmp_path / "o.json", {})


def test_the_engine_argv_is_what_the_nimble_script_parses(tmp_path):
    """The seam: engines.py writes the argv, harness/nimble_score.py reads it."""
    from harness import nimble_score
    eng = engines.resolve(f"nimble:{NIMBLE},revision=abc,temperature=2.0")
    a = eng.argv("p", tmp_path / "o.json", {"schema": SPEC, "context": "ctx"})
    got = nimble_score.parse_args(a[1:])
    assert (got.model, got.revision, got.context, got.temperature) == (NIMBLE, "abc",
                                                                        "ctx", 2.0)
    assert json.loads(got.schema) == SPEC and got.out == str(tmp_path / "o.json")


def test_a_nimble_run_through_the_process_runner_is_scored(monkeypatch, tmp_path):
    """A fake scorer stands in for nimble; the row is scored like any other.

    Run as [sys.executable, script, <the engine's own args>]: Windows cannot
    exec a #! script (WinError 193), and the args are still the engine's.
    """
    import dataclasses
    import sys

    from evals.runners.process import ProcessRunner
    fake = tmp_path / "fake_nimble.py"
    fake.write_text(
        "import json, sys\na = sys.argv\n"
        "out = a[a.index('--out') + 1]\n"
        "json.dump({'answers': {'route': 'tech', 'urgent': False}, 'probabilities': "
        "{'route': {'billing': 0.1, 'tech': 0.9}, 'urgent': {'false': 0.8, 'true': 0.2}}},"
        " open(out, 'w', encoding='utf-8'))\n", encoding="utf-8")
    real = engines.resolve(f"nimble:{NIMBLE}")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [
        sys.executable, str(fake), *real.argv(p, o, params)[1:]])
    c = Case(id="d", modality="decide", prompt="p", context="ctx", params={"schema": SPEC},
             assertions={"answers": {"route": "tech", "urgent": False}})
    r = ProcessRunner(eng, tmp_path / "out").run(c)
    assert r.passed, r.detail
    assert r.metrics["calibrated"] == 1.0
    assert r.metrics["decide_brier_sum"] == pytest.approx(0.02 + 0.08)


def test_the_nimble_script_writes_the_scorers_answers_and_probabilities(tmp_path):
    from harness import nimble_score

    class Scorer:
        def score(self, context, schema):
            assert context == "ctx" and schema == SPEC
            return {"model": NIMBLE, "revision": "r", "temperature": 1.0,
                    "output": {"route": "tech", "urgent": True},
                    "fields": {"route": {"scores": {"billing": 0.3, "tech": 0.7}},
                               "urgent": {"scores": {"false": 0.4, "true": 0.6}}}}

    out = tmp_path / "o.json"
    args = nimble_score.parse_args(["--model", NIMBLE, "--context", "ctx", "--schema",
                                    json.dumps(SPEC), "--out", str(out), "--models", "m"])
    nimble_score.run(args, scorer_factory=lambda s, t: Scorer(),
                     settings={"model_id": NIMBLE, "revision": "r"})
    got = decide.parse(out.read_text(encoding="utf-8"), SPEC)
    assert got["urgent"] == {"answer": "true", "probs": {"false": 0.4, "true": 0.6}}


def test_an_adapter_is_merged_once_onto_its_pinned_base(monkeypatch, tmp_path):
    import sys
    import types

    from harness import nimble_score
    snap = tmp_path / "snapshots" / "rev1"
    snap.mkdir(parents=True)
    (snap / "adapter_config.json").write_text("{}", encoding="utf-8")
    (snap / "schema_config.json").write_text(json.dumps(
        {"model": "Qwen/Qwen3.5-9B", "revision": "base1", "max_length": 8192}), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(
        snapshot_download=lambda repo, revision=None: str(snap)))
    merges = []

    def merge(s, contract, out, repo):
        merges.append(contract["revision"])
        out.mkdir(parents=True)
        (out / "READY.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(nimble_score, "merge", merge)
    got = nimble_score.prepare(NIMBLE, None, str(tmp_path / "models"))
    assert got["model_path"].endswith("Bespoke-Nimble-9B-rev1")
    assert got["max_input_tokens"] == 8192 and merges == ["base1"]
    nimble_score.prepare(NIMBLE, None, str(tmp_path / "models"))
    assert merges == ["base1"]


# --- the ladder -----------------------------------------------------------------

def test_decide_is_a_named_lane_in_every_table():
    from harness import discover, verify, winners
    assert "decide" in lanes.ALL
    assert screen.LANE_CANDIDATES["decide"]
    assert "decide" in verify.COST_S and "decide" in winners.FAMILIES
    assert "decide" in winners.typed()
    assert discover.lane_queries("decide")
    assert "decide" in core.CHECKERS


@pytest.mark.parametrize("repo", [
    "crh225/plumb-4b-GGUF", "mindchain/imajev-4b-GGUF",
    "apus-ailab/APUS-OpenJev-v1-4B-GGUF", "Mapika/decider-4b-GGUF"])
def test_a_jev_class_model_is_reachable_by_a_decide_query(repo):
    from harness import discover
    # HF search matches a substring of the repo id, so one query must be in it (#311).
    queries = [q.lower() for q in discover.lane_queries("decide")]
    assert any(q in repo.lower() for q in queries), queries


def test_an_adapter_is_spelled_for_the_engine_that_loads_it():
    assert screen.candidate_for("decide", NIMBLE, "lora") == f"nimble:{NIMBLE}"
    assert screen.candidate_for("decide", "org/full-model") == "org/full-model"
    assert screen.candidate_for("decide", NIMBLE, "comfyui") == ""
    assert screen.candidate_for("image", "org/style-lora", "lora") == ""
    assert screen.takes_attachment("decide", "lora")
    assert not screen.takes_attachment("image", "lora")


def test_rank_keeps_an_adapter_only_where_an_engine_loads_it():
    from harness import rank

    def row(name, lane, attaches):
        return {"name": name, "lane": lane, "description": "", "times": 2,
                "registry": "huggingface", "attaches_to": attaches,
                "runtime_needed": "", "parents": []}
    got = rank.rank([row(NIMBLE, "decide", "lora"), row("org/style-lora", "image", "lora"),
                     row("org/nodes", "decide", "comfyui")],
                    serving=(), measured_lanes=(), ceiling_gib=64.0)
    assert [r["name"] for r in got] == [NIMBLE]


def test_the_nimble_card_lands_in_decide_as_an_adapter():
    from harness import inspect as ins
    card = {"pipeline_tag": "text-classification", "library_name": "peft",
            "tags": ["peft", "lora", "qwen3.5", "text-classification",
                     "structured-prediction", "base_model:adapter:Qwen/Qwen3.5-9B"]}
    facts = ins.card_facts(card)
    assert facts.lane == "decide" and facts.attaches_to == "lora"
    assert ("Qwen/Qwen3.5-9B", "adapter") in facts.parents
    v2 = {"library_name": "peft", "tags": ["peft", "lora", "structured-prediction"]}
    assert ins.lane_for(v2) == "decide"


def test_an_adapter_download_is_loadable_and_needs_its_base(tmp_path):
    from harness import downloads
    snap = tmp_path / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "adapter_config.json").write_text(json.dumps(
        {"base_model_name_or_path": "Qwen/Qwen3.5-9B", "peft_type": "LORA"}), encoding="utf-8")
    assert downloads.loadable(downloads.HUB, tmp_path)
    cfg = downloads.config_of(tmp_path)
    assert downloads.requires_in(cfg, NIMBLE) == ["Qwen/Qwen3.5-9B"]


def test_the_fetch_tier_knows_an_adapters_base_before_downloading_it():
    from harness import fetching
    from harness import inspect as ins
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        ms.record(conn, ms.Seen(name=NIMBLE, source="t"))
        ms.set_card(conn, NIMBLE, ins.card_facts(
            {"pipeline_tag": "text-classification", "library_name": "peft",
             "tags": ["lora", "base_model:adapter:Qwen/Qwen3.5-9B"]}))
        assert fetching.requires(NIMBLE, conn) == ["Qwen/Qwen3.5-9B"]
        assert set(fetching.missing(NIMBLE, conn)) == {NIMBLE, "Qwen/Qwen3.5-9B"}
    finally:
        conn.close()


def test_the_migration_gives_a_queued_laneless_card_its_lane(tmp_path):
    from harness import memory_store as ms
    db = tmp_path / "s.db"
    conn = ms.connect(db)
    try:
        for name in (NIMBLE, "org/v2", "org/a-tool", "org/coded"):
            ms.record(conn, ms.Seen(name=name, source="t"))
        conn.execute("UPDATE proposals SET hf_task = 'text-classification' "
                     "WHERE name = ?", (NIMBLE,))
        conn.execute("UPDATE proposals SET card_tags = '[\"lora\", "
                     "\"structured-prediction\"]' WHERE name = 'org/v2'")
        conn.execute("UPDATE proposals SET lane = 'code', hf_task = "
                     "'text-generation' WHERE name = 'org/coded'")
        # The schema before this one, pinned as a literal (RULE #405).
        conn.execute("UPDATE meta SET value = '38' WHERE key = 'schema'")
        conn.commit()
    finally:
        conn.close()
    conn = ms.connect(db)
    try:
        got = dict(conn.execute("SELECT name, lane FROM proposals").fetchall())
    finally:
        conn.close()
    assert got[NIMBLE] == "decide" and got["org/v2"] == "decide"
    assert got["org/a-tool"] == "" and got["org/coded"] == "code"


def test_the_prose_names_decide_without_swallowing_other_classifiers():
    assert lanes.from_prose("a typed decision model with calibrated probabilities") == "decide"
    assert lanes.from_prose("an audio classification model") == ""
    assert re.search(r"decide", run.ALL_MODALITIES.__repr__())


# --- the decider engine (strands-decider) ---------------------------------------

DECIDER = "StrandsAgents/strands-decider-2B-hobson-v21"
DECIDER_CARD = {"library": "peft", "card_tags": json.dumps(
    ["peft", "strands-decider", "decision-model", "lora", "text-classification"]),
    "parents": [("Qwen/Qwen3.5-2B-Base", "adapter")]}
NIMBLE_CARD = {"library": "peft", "card_tags": ["peft", "lora", "structured-prediction"],
               "parents": [("Qwen/Qwen3.5-9B", "adapter")]}


def _fake_ask(path, device, context, qs):
    """System One answers for whatever questions the mapping asked."""
    out = {}
    for name, q in qs.items():
        if q["type"] == "noul":
            out[name] = {"type": "noul", "noul": 0.7}
        else:
            opts = list(q["criteria"])
            probs = {o: (0.8 if i == 1 else 0.2 / (len(opts) - 1)) for i, o in enumerate(opts)}
            out[name] = {"type": "choice", "choice": opts[1], "probabilities": probs,
                         "confidence": 0.5}
    return {"model": "m", "answers": out, "usage": {}}


def test_decider_is_a_decide_engine_that_loads_adapters():
    eng = engines.resolve(f"decider:{DECIDER}")
    assert (eng.modality, eng.output_suffix, eng.name) == (
        "decide", ".json", "decider/strands-decider-2B-hobson-v21")
    assert engines.loads_adapters(f"decider:{DECIDER}")
    assert run.kind_of(f"decider:{DECIDER}") == "process"
    assert run.modality_of(f"decider:{DECIDER}") == "decide"
    with pytest.raises(ValueError, match="unknown option"):
        engines.resolve(f"decider:{DECIDER},temperature=2")


def test_the_engine_argv_is_what_the_decider_script_parses(tmp_path):
    from harness import decider_score
    eng = engines.resolve(f"decider:{DECIDER},revision=abc,device=cpu")
    a = eng.argv("p", tmp_path / "o.json", {"schema": SPEC, "context": "ctx"})
    got = decider_score.parse_args(a[1:])
    assert (got.model, got.revision, got.context, got.device) == (DECIDER, "abc", "ctx", "cpu")
    assert json.loads(got.schema) == SPEC and got.out == str(tmp_path / "o.json")
    with pytest.raises(ValueError, match="no schema"):
        eng.argv("p", tmp_path / "o.json", {})


def test_enum_fields_are_choice_and_booleans_are_noul_questions():
    from harness import decider_score
    schema = {"route": {"type": "enum", "choices": ["billing", "tech"], "description": "Route?",
                        "choice_descriptions": {"tech": "bugs"}},
              "urgent": {"type": "boolean", "description": "Urgent?",
                         "choice_descriptions": {"true": "now"}},
              "level": {"type": "enum", "choices": [0, 1, 2], "description": "Rate"}}
    q = decider_score.questions(schema)
    assert q["route"] == {"type": "choice", "instructions": "Route?",
                          "criteria": {"billing": None, "tech": "bugs"}}
    assert q["urgent"] == {"type": "noul", "instructions": "Urgent?",
                           "criteria": {"true": "now"}}
    assert list(q["level"]["criteria"]) == ["0", "1", "2"]


def test_p_true_becomes_the_boolean_fields_distribution(tmp_path):
    from harness import decider_score
    out = tmp_path / "o.json"
    args = decider_score.parse_args(["--model", DECIDER, "--context", "ctx", "--schema",
                                     json.dumps(SPEC), "--out", str(out), "--device", "cpu"])
    body = decider_score.run(args, ask=_fake_ask, resolve=lambda m, r: ("p", "rev1"))
    assert body["revision"] == "rev1" and body["device"] == "cpu"
    got = decide.parse(out.read_text(encoding="utf-8"), SPEC)
    assert got["urgent"]["answer"] == "true"
    assert got["urgent"]["probs"] == pytest.approx({"false": 0.3, "true": 0.7})
    assert got["route"]["answer"] == "tech"
    assert got["route"]["probs"] == pytest.approx({"billing": 0.2, "tech": 0.8})


def test_a_decider_run_through_the_process_runner_is_scored(tmp_path):
    """The real mapping behind a fake System One engine, run as
    [sys.executable, script, <the engine's own args>] (WinError 193)."""
    import dataclasses
    import sys

    from evals.runners.process import ProcessRunner
    fake = tmp_path / "fake_decider.py"
    fake.write_text(
        "import sys\n"
        f"sys.path[:0] = [{str(ROOT)!r}, {str(Path(__file__).parent)!r}]\n"
        "from harness import decider_score\n"
        "from test_decide_lane import _fake_ask\n"
        "decider_score.run(decider_score.parse_args(sys.argv[1:] + ['--device', 'cpu']),\n"
        "                  ask=_fake_ask, resolve=lambda m, r: ('p', 'r'))\n",
        encoding="utf-8")
    real = engines.resolve(f"decider:{DECIDER}")
    eng = dataclasses.replace(real, argv=lambda p, o, params: [
        sys.executable, str(fake), *real.argv(p, o, params)[1:]])
    c = Case(id="d", modality="decide", prompt="p", context="ctx", params={"schema": SPEC},
             assertions={"answers": {"route": "tech", "urgent": True}})
    r = ProcessRunner(eng, tmp_path / "out").run(c)
    assert r.passed, r.detail
    assert r.metrics["calibrated"] == 1.0
    assert r.metrics["decide_brier_sum"] == pytest.approx(0.08 + 0.18)


def test_an_adapters_engine_is_named_by_its_card_not_its_lane():
    assert engines.adapter_engine(DECIDER, DECIDER_CARD) == "decider"
    assert engines.adapter_engine("org/renamed", DECIDER_CARD) == "decider"
    assert engines.adapter_engine("org/x", {"library": "strands-decider"}) == "decider"
    assert engines.adapter_engine("org/ft", {"parents": [(DECIDER, "finetune")]}) == "decider"
    assert engines.adapter_engine(NIMBLE, NIMBLE_CARD) == "nimble"
    assert engines.adapter_engine("org/qwen-lora", NIMBLE_CARD) == ""
    assert engines.adapter_engine("org/nimble-strands-decider", None) == ""
    assert screen.candidate_for("decide", DECIDER, "lora", card=DECIDER_CARD) == \
        f"decider:{DECIDER}"
    assert screen.candidate_for("decide", NIMBLE, "lora", card=NIMBLE_CARD) == \
        f"nimble:{NIMBLE}"


def test_an_adapter_no_card_identifies_has_no_runner_and_is_reported():
    from harness import rank
    row = {"name": "org/qwen-lora", "lane": "decide", "attaches_to": "lora",
           "library": "peft", "card_tags": '["lora"]',
           "parents": [("Qwen/Qwen3.5-9B", "adapter")]}
    assert screen.candidate_for("decide", row["name"], "lora", card=row) == ""
    gap = screen.runner_gap("decide", row["name"], "lora", card=row)
    assert "no decide engine is known to load this lora" in gap
    assert [r["name"] for r in rank.runnerless([row])] == ["org/qwen-lora"]
    planned = screen.plan([row], missing=lambda n: [])[0]
    assert (planned["state"], planned["why_not"]) == (screen.NO_RUNNER, gap)
    ok = {**row, "name": DECIDER, "card_tags": DECIDER_CARD["card_tags"]}
    assert screen.runner_gap("decide", DECIDER, "lora", card=ok) == ""
    assert rank.runnerless([ok]) == []


def test_the_store_card_picks_the_engine(tmp_path):
    from harness import candidates
    from harness import inspect as ins
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    try:
        ms.record(conn, ms.Seen(name="org/my-router", source="t", lane="decide"))
        ms.set_card(conn, "org/my-router", ins.card_facts(
            {"pipeline_tag": "text-classification", "library_name": "peft",
             "tags": ["lora", "strands-decider", "base_model:adapter:Qwen/Qwen3.5-2B-Base"]}))
        assert screen.candidate_for("decide", "org/my-router", "lora", conn=conn) == \
            "decider:org/my-router"
        assert candidates.for_proposal(conn, "decide", "org/my-router", "lora") == \
            "decider:org/my-router"
        assert screen.candidate_for("decide", "org/my-router", "lora") == ""
    finally:
        conn.close()


def test_the_fetch_tier_queues_an_adapter_no_engine_is_known_to_load(tmp_path):
    from harness import fetching
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")
    try:
        import fakes
        ms.record(conn, ms.Seen(name="org/qwen-lora", source="t", lane="decide",
                                registry="huggingface", resolved="org/qwen-lora"))
        ms.set_size(conn, "org/qwen-lora", 104857600)
        fakes.carded(conn, "org/qwen-lora", {
            "library_name": "peft", "tags": ["lora", "base_model:adapter:Qwen/Qwen3.5-9B"]})
        ms.decide(conn, "org/qwen-lora", "queued", tier="inspect", detail="fits")
        got = fetching.run(conn, {"org/qwen-lora": 100 * 1024 ** 2}, limit=1,
                           snapshot=lambda *a, **k: pytest.fail("no engine loads it"))
        assert got and not got[0]["ok"]
        assert "no decide engine is known to load" in got[0]["why"]
        state = conn.execute("SELECT state FROM proposals WHERE name = ?",
                             ("org/qwen-lora",)).fetchone()["state"]
        assert state == "queued"
    finally:
        conn.close()
