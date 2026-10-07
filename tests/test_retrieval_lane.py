"""The retrieval lane: rank a labelled corpus for a query, scored on recall@k and nDCG. #563."""
import dataclasses
import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals import run  # noqa: E402
from evals.core import Case, load_cases, score, summarize  # noqa: E402
from harness import discover, engines, inspect as ins, lanes, screen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RECURRING = ("Contrastive-LM/CLM-v0.1-8B", "cross-encoder/ettin-reranker-1b-v1",
             "tencent/EVIE-8B", "tencent/EVIE-Preview-4.5B")


def _load():
    try:
        return load_cases(ROOT / "evals" / "cases" / "retrieval")
    except ValueError:
        return []


CASES = _load()


def _corpus():
    path = ROOT / "evals" / "cases" / "retrieval" / "corpus.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- the lane --------------------------------------------------------------

def test_retrieval_is_wanted_after_ocr():
    assert lanes.WANTED.index("retrieval") == lanes.WANTED.index("ocr") + 1


# --- routing ---------------------------------------------------------------

@pytest.mark.parametrize("repo", ["Contrastive-LM/CLM-v0.1-8B",
                                  "cross-encoder/ettin-reranker-1b-v1",
                                  "tencent/EVIE-Preview-4.5B"])
def test_each_recorded_recurring_retriever_routes_to_retrieval(repo):
    import fakes
    assert ins.lane_for(fakes.card(repo)) == "retrieval"


@pytest.mark.parametrize("task,tags,lane", [
    ("text-ranking", [], "retrieval"),
    ("text-retrieval", [], "retrieval"),
    ("visual-document-retrieval", [], "retrieval"),
    ("sentence-similarity", ["dense-retrieval"], "retrieval"),
    ("feature-extraction", ["reranker"], "retrieval"),
    # A general sentence embedder is not clearly a retriever.
    ("sentence-similarity", ["mteb"], ""),
    ("feature-extraction", [], ""),
    # A classifier stays a decision even when it reranks.
    ("text-classification", ["reranker"], "decide"),
    # A text model that mentions retrieval is still a text model.
    ("text-generation", ["rag"], "code"),
])
def test_retrieval_routing_steals_nothing_from_other_lanes(task, tags, lane):
    assert ins.lane_for({"pipeline_tag": task, "tags": tags}) == lane


def test_recorded_negative_controls_keep_their_lanes():
    import fakes
    assert ins.lane_for(fakes.card("sentence-transformers/all-MiniLM-L6-v2")) == ""
    assert ins.lane_for(fakes.card("BAAI/bge-reranker-base")) == "decide"


def test_a_reranker_tagged_for_an_inference_server_is_not_an_attachment():
    """`text-embeddings-inference` holds `embedding`, which once marked every reranker an attachment."""
    import fakes
    assert ins.card_facts(fakes.card("cross-encoder/ettin-reranker-1b-v1")).attaches_to == ""
    assert screen.is_attachment("textual_inversion embedding for sdxl")


@pytest.mark.parametrize("repo", RECURRING)
def test_each_recurring_retriever_is_reachable_by_a_retrieval_query(repo):
    queries = [q.lower() for q in discover.lane_queries("retrieval")]
    assert any(q in repo.lower() for q in queries), queries


# --- the cases -------------------------------------------------------------

def test_the_lane_has_enough_labelled_queries_over_one_corpus():
    assert len(CASES) >= 12
    ids = {d["id"] for d in _corpus()}
    assert len(ids) >= 25
    for c in CASES:
        assert c.input_file.name == "corpus.jsonl"
        assert set(c.assertions["relevant"]) <= ids and c.assertions["relevant"]


def test_a_case_whose_relevant_ids_are_not_in_its_corpus_is_refused(tmp_path):
    (tmp_path / "corpus.jsonl").write_text('{"id": "a", "text": "x"}\n', encoding="utf-8")
    (tmp_path / "c.yaml").write_text("id: c\nmodality: retrieval\nprompt: q\n"
                                     "input_file: corpus.jsonl\nassert: {relevant: [b]}\n",
                                     encoding="utf-8")
    with pytest.raises(ValueError, match="not in"):
        load_cases(tmp_path)


# --- the metric and its negative control -----------------------------------

def _rows(rank_for):
    rows = []
    for c in CASES:
        r = score(c, json.dumps({"ranking": rank_for(c)}))
        r.candidate = "stub"
        rows.append(r)
    return summarize(rows)["stub"]


def test_the_metric_numbers_on_a_known_ranking():
    from harness.checks import retrieval
    assert retrieval.recall_at(["a", "b", "c"], {"c", "z"}, 2) == 0.0
    assert retrieval.recall_at(["a", "b", "c"], {"c", "z"}, 3) == 0.5
    assert retrieval.ndcg_at(["r", "x"], {"r"}, 10) == 1.0
    assert retrieval.ndcg_at(["x", "r"], {"r"}, 10) == pytest.approx(1 / 1.5849625, rel=1e-6)
    assert retrieval.ndcg_at(["r", "r", "x"], {"r"}, 10) == 1.0


def test_negative_control_a_wrong_ranker_scores_clearly_worse():
    """A ranker that puts the relevant documents last, and a seeded shuffle, against a right one."""
    ids = [d["id"] for d in _corpus()]

    def right(c):
        rel = c.assertions["relevant"]
        return rel + [i for i in ids if i not in rel]

    def worst(c):
        rel = c.assertions["relevant"]
        return [i for i in ids if i not in rel] + rel

    def shuffled(c):
        got = list(ids)
        random.Random(c.id).shuffle(got)
        return got
    good, bad, chance = _rows(right), _rows(worst), _rows(shuffled)
    assert good["metrics"]["retrieval_recall"] == 1.0 == good["metrics"]["retrieval_ndcg"]
    assert bad["passed"] == 0 and bad["metrics"]["retrieval_recall"] == 0.0
    assert chance["metrics"]["retrieval_recall"] < 0.5 < good["metrics"]["retrieval_recall"]


def test_an_unparseable_ranking_fails_rather_than_scoring_zero_quietly():
    r = score(CASES[0], "not json")
    assert not r.passed and "ranking" in r.detail


def test_the_lexical_baseline_is_between_the_controls():
    """BM25 is the incumbent: better than chance, short of perfect on paraphrased queries."""
    from harness import lexical_rank
    docs = _corpus()
    got = _rows(lambda c: lexical_rank.rank(c.prompt, docs))
    assert 0.5 <= got["metrics"]["retrieval_recall"] < 1.0


# --- engines and the runner ------------------------------------------------

def test_bm25_is_a_weightless_process_engine(tmp_path):
    from harness import disk
    e = engines.resolve("bm25")
    assert e.modality == "retrieval" and e.output_suffix == ".json"
    argv = e.argv("a query", tmp_path / "o.json", {"input": "/c/corpus.jsonl"})
    assert "harness.lexical_rank" in argv and "/c/corpus.jsonl" in argv
    with pytest.raises(ValueError, match="takes no model"):
        engines.resolve("bm25:org/model")
    assert "bm25" in disk.WEIGHTLESS


@pytest.mark.parametrize("head,mode", [("rerank", "cross"), ("embed", "bi")])
def test_the_transformers_retrievers_are_process_engines(head, mode, tmp_path):
    e = engines.resolve(f"{head}:org/m,device=cpu")
    argv = e.argv("q", tmp_path / "o.json", {"input": "/c/corpus.jsonl"})
    assert argv[1] == "rank" and argv[argv.index("--mode") + 1] == mode
    assert argv[argv.index("--corpus") + 1] == "/c/corpus.jsonl"
    assert argv[argv.index("--query") + 1] == "q"
    with pytest.raises(ValueError, match="needs a model"):
        engines.resolve(f"{head}:")


def test_the_lane_spells_a_reranker_by_default_and_an_embedder_by_its_card():
    assert screen.candidate_for("retrieval", "org/m") == "rerank:org/m"
    card = {"hf_task": "sentence-similarity", "library": "sentence-transformers",
            "card_tags": ["dense-retrieval"]}
    assert screen.candidate_for("retrieval", "org/e", card=card) == "embed:org/e"
    assert screen.candidate_for("retrieval", "bm25") == "bm25"


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/engines.py:TASK_ENGINES")
@pytest.mark.parametrize("task", ["", "text-classification", "a-task-nobody-has-named-yet"])
def test_a_task_the_table_does_not_name_keeps_the_lanes_own_order(task):
    """The fallback is the lane's incumbent-first order, never a guess at an engine."""
    specs = screen.LANE_CANDIDATES["retrieval"]
    assert engines.by_card(specs, {"hf_task": task}) == specs
    assert engines.by_card(specs, None) == specs
    # Every task the table names is one inspect files under retrieval when tagged so.
    for named in engines.TASK_ENGINES:
        assert ins.lane_for({"pipeline_tag": named, "tags": ["reranker"]}) == "retrieval"


@pytest.mark.parametrize("repo,why", [
    ("Contrastive-LM/CLM-v0.1-8B", "contrastive-lm"),
    ("tencent/EVIE-Preview-4.5B", "page images"),
])
def test_a_retriever_this_harness_cannot_load_is_a_runner_wanted(repo, why):
    import fakes
    card = fakes.card(repo)
    row = {"name": repo, "lane": "retrieval", "hf_task": card["pipeline_tag"],
           "library": card["library_name"], "card_tags": card["tags"]}
    assert why in screen.runner_gap("retrieval", repo, card=row)
    assert screen.plan([row], missing=lambda n: [])[0]["state"] == screen.NO_RUNNER


def test_a_loadable_reranker_has_no_runner_gap():
    import fakes
    card = fakes.card("cross-encoder/ettin-reranker-1b-v1")
    row = {"name": "x", "hf_task": card["pipeline_tag"], "library": card["library_name"],
           "card_tags": card["tags"]}
    assert screen.runner_gap("retrieval", "cross-encoder/ettin-reranker-1b-v1", card=row) == ""


def test_run_selects_only_retrieval_cases_for_a_retrieval_engine():
    mixed = [Case(id="r", modality="retrieval", prompt="p"), Case(id="c", modality="code", prompt="p")]
    assert [c.id for c in run.cases_for("bm25", mixed)] == ["r"]
    assert "r" not in [c.id for c in run.cases_for("q3-4b", mixed)]


def test_the_typed_default_is_bm25():
    from harness import cli, verify, winners
    assert winners.typed()["retrieval"] == cli.DEFAULT_RETRIEVAL_ENGINE == "bm25"
    assert winners.FAMILIES["retrieval"] == "engine"
    assert verify.COST_S["retrieval"] > 0


def test_a_bm25_run_through_the_process_runner_is_scored(tmp_path):
    from evals.runners.process import ProcessRunner
    case = next(c for c in CASES if c.id == "retrieval-linux-ocr")
    r = ProcessRunner(engines.resolve("bm25"), tmp_path).run(case)
    assert r.passed, r.detail
    assert r.metrics["retrieval_recall"] == 1.0


# --- the script that runs in the transformers venv -------------------------

@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:HF_TASK_BIN")
def test_the_rank_argv_is_what_hf_task_accepts(monkeypatch, tmp_path):
    from harness import hf_task
    monkeypatch.delenv("HF_TASK_BIN", raising=False)
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"id": "a", "text": "alpha"}\n{"id": "b", "text": "beta"}\n',
                      encoding="utf-8")
    out = tmp_path / "o.json"
    argv = engines.resolve("embed:m/e").argv("beta?", out, {"input": str(corpus)})
    assert Path(argv[0]) == ROOT / "scripts" / "hf-task.sh"

    def scores(mode, model, query, texts):
        assert (mode, model, query, texts) == ("bi", "m/e", "beta?", ["alpha", "beta"])
        return [0.1, 0.9]
    assert hf_task.main(argv[1:], score=scores) == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"ranking": ["b", "a"]}


def test_a_remote_code_retriever_is_refused(tmp_path, capsys):
    from harness import hf_task, reasons
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"id": "a", "text": "alpha"}\n', encoding="utf-8")

    def needs_code(*a):
        raise ValueError("... Please pass the argument `trust_remote_code=True` ...")
    rc = hf_task.main(["rank", "--mode", "cross", "--model", "m/x", "--query", "q",
                       "--corpus", str(corpus), "--out", str(tmp_path / "o.json")],
                      score=needs_code)
    assert rc == hf_task.NEEDS_OWN_RUNNER
    assert reasons.classify(capsys.readouterr().err, candidate="rerank:m/x") \
        == reasons.LOAD_FAILED_LAYOUT


def test_weights_not_on_disk_offline_are_the_harness_not_the_model():
    """Measured: embed:BAAI/bge-large-en-v1.5 half-cached under HF_HUB_OFFLINE=1. #563."""
    from harness import reasons
    msg = ("exit 1: Check your internet connection or see how to run the library in "
           "offline mode at 'https://huggingface.co/docs/transformers/installation#offline-mode'.")
    assert reasons.classify(msg, candidate="embed:BAAI/bge-large-en-v1.5") == reasons.HARNESS_ERROR


# --- the store -------------------------------------------------------------

def test_a_stored_reranker_marked_an_embedding_attachment_is_released_and_relaned(tmp_path):
    from harness import memory_store as ms
    from harness.memory_store.migrations import retractions
    conn = ms.connect(tmp_path / "d.db")
    tags = json.dumps(["sentence-transformers", "reranker", "text-embeddings-inference"])
    conn.execute("INSERT INTO proposals (name, lane, hf_task, library, card_tags, attaches_to,"
                 " first_seen, last_seen) VALUES ('a/rr', '', 'text-ranking',"
                 " 'sentence-transformers', ?, 'embedding', 0, 0)", (tags,))
    conn.execute("INSERT INTO proposals (name, lane, hf_task, card_tags, attaches_to,"
                 " first_seen, last_seen) VALUES ('b/ti', '', 'text-to-image', ?, 'embedding',"
                 " 0, 0)", (json.dumps(["textual_inversion", "embedding"]),))
    retractions._release_retrievers_marked_embeddings(conn)
    retractions._relane_the_laneless_from_lineage(conn)
    got = {r["name"]: (r["lane"], r["attaches_to"]) for r in
           conn.execute("SELECT name, lane, attaches_to FROM proposals")}
    assert got["a/rr"] == ("retrieval", "")
    assert got["b/ti"][1] == "embedding"
    assert ms.SCHEMA_VERSION >= 54
