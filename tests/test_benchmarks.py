"""Benchmark discovery: sweep, contamination, import, listing. #491, #470."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from evals import benchmark_import as bi
from evals.core import load_cases
from harness import benchmarks as bm
from harness import contamination as ct
from harness import memory_store as ms
from harness.checks import code

FIX = Path(__file__).resolve().parent / "fixtures" / "benchmarks"


def fixture(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def search_entry(repo: str) -> dict:
    return next(e for e in fixture("hf_datasets_search.json") if e["id"] == repo)


# ---- facts from a registry entry --------------------------------------------

def test_a_huggingface_entry_becomes_a_benchmark_with_its_facts():
    b = bm.from_hf(search_entry("evalplus/mbppplus"), "code")
    assert b.name == "hf:evalplus/mbppplus"
    assert (b.registry, b.lane, b.license) == ("huggingface", "code", "apache-2.0")
    assert (b.created, b.updated) == ("2024-01-23", "2024-04-17")
    assert b.size == "n<1K" and b.gated == ""
    assert b.url == "https://huggingface.co/datasets/evalplus/mbppplus"


def test_a_gated_dataset_says_how_it_is_gated():
    entry = {**search_entry("evalplus/mbppplus"), "gated": "manual"}
    assert bm.from_hf(entry, "code").gated == "manual"


def test_a_github_repo_becomes_a_benchmark_with_its_license_or_none():
    items = fixture("github_search.json")["items"]
    licensed = bm.from_github(items[2], "svg")
    assert licensed.name == "gh:isayrhythm/pelican-benchmark"
    assert (licensed.registry, licensed.license, licensed.created) == (
        "github", "mit", "2026-09-30")
    assert bm.from_github(items[0], "svg").license == ""


@pytest.mark.parametrize("features, fmt", [
    (["id", "raw_solution", "test_code", "raw_problem", "new_solution", "new_problem"],
     "self-invoking-python"),
    (["task_id", "code", "prompt", "test_list"], "assert-list-python"),
    (["content", "label"], "labelled-text"),
    (["question", "answer", "choices"], "multiple-choice"),
    (["image", "caption"], ""),
])
def test_the_task_format_is_read_from_the_columns(features, fmt):
    assert bm.task_format(features) == fmt


def test_the_dataset_info_supplies_columns_size_and_revision():
    info = fixture("hf_dataset_mbpp-pro.json")
    b = bm.from_hf(info, "code")
    assert b.task_format == "self-invoking-python"
    assert b.rows == 378
    assert b.revision == "50f18448e09a8383226e1a5cd3654d2a454fe333"


# ---- the sweep -----------------------------------------------------------------

class Fetcher:
    """Fixture registry answers by URL prefix; records every request."""

    def __init__(self, answers: dict, fail: tuple = ()):
        self.answers, self.fail, self.asked = answers, fail, []

    def __call__(self, url: str, params: dict | None = None):
        self.asked.append((url, dict(params or {})))
        for prefix in self.fail:
            if url.startswith(prefix):
                raise RuntimeError("registry down")
        for prefix, body in self.answers.items():
            if url.startswith(prefix):
                return body
        raise AssertionError(f"unexpected request {url}")


def registry(fail=()):
    return Fetcher({bm.HF_DATASETS: fixture("hf_datasets_search.json"),
                    bm.GH_SEARCH: fixture("github_search.json")}, fail)


def test_a_sweep_records_every_source_it_found_in_the_store():
    conn = ms.connect()
    found = bm.sweep(conn, lanes=["code"], get=registry(), now=1000.0)
    names = {r["name"] for r in ms.benchmarks(conn, "code")}
    assert "hf:evalplus/mbppplus" in names
    assert "gh:isayrhythm/pelican-benchmark" in names
    assert {b.name for b in found} == names
    row = ms.source_row(conn, "benchmarks:huggingface:code")
    assert row["last_status"] == "ok" and row["kind"] == "benchmarks"


def test_a_sweep_asks_for_the_newest_and_the_most_used():
    """Newest alone surfaces mirrors and re-uploads; the canonical sources are the most liked."""
    conn = ms.connect()
    get = registry()
    bm.sweep(conn, lanes=["code"], get=get, now=1000.0)
    sorts = {p.get("sort") for u, p in get.asked if u == bm.HF_DATASETS}
    assert sorts == {"createdAt", "likes"}


def test_a_candidate_scoped_to_another_lane_does_not_date_this_one():
    training = [{**TRAINING[1], "lane": "code"},
                {"candidate": "StrandsAgents/strands-decider-2B-hobson-v21", "lane": "decide",
                 "cutoff": "2026-10-05", "datasets": []}]
    b = bm.Benchmark(name="hf:org/new", registry="huggingface", lane="code", created="2026-09-01")
    assert bm.contamination(b, training)[0] == "after-cutoff"
    b.lane = "decide"
    assert bm.contamination(b, training)[0] == "predates"


def test_a_sweep_drops_entries_below_the_popularity_floor():
    conn = ms.connect()
    bm.sweep(conn, lanes=["code"], get=registry(), now=1000.0)
    names = {r["name"] for r in ms.benchmarks(conn, "code")}
    assert "hf:CodeKaleidoscope/Dynamic_MBPP_sanitized" not in names


def test_a_failing_registry_is_recorded_and_the_other_still_read():
    conn = ms.connect()
    bm.sweep(conn, lanes=["code"], get=registry(fail=(bm.HF_DATASETS,)), now=1000.0)
    assert ms.source_row(conn, "benchmarks:huggingface:code")["last_status"] == "failed"
    assert any(r["registry"] == "github" for r in ms.benchmarks(conn, "code"))


def test_a_sweep_inside_the_interval_asks_nothing_unless_forced():
    conn = ms.connect()
    bm.sweep(conn, lanes=["code"], get=registry(), now=1000.0)
    again = registry()
    bm.sweep(conn, lanes=["code"], get=again, now=1060.0)
    assert again.asked == []
    bm.sweep(conn, lanes=["code"], get=again, now=1060.0, force=True)
    assert again.asked


def test_a_resweep_updates_a_source_rather_than_duplicating_it():
    conn = ms.connect()
    bm.sweep(conn, lanes=["code"], get=registry(), now=1000.0, force=True)
    n = len(ms.benchmarks(conn))
    bm.sweep(conn, lanes=["code"], get=registry(), now=2000.0, force=True)
    assert len(ms.benchmarks(conn)) == n


def test_every_lane_the_issue_names_has_queries():
    for lane in ("code", "decide", "svg", "web", "extract", "tts", "image"):
        assert bm.LANE_QUERIES[lane], lane


# ---- cutoffs and declared training data (#414, #470) ----------------------------

def test_a_quantization_takes_its_parents_release_date():
    facts = bm.training_facts(fixture("model_qwen3-4b-mlx.json"),
                              parent=fixture("model_qwen3-4b.json"))
    assert facts["cutoff"] == "2025-08-05"
    assert facts["cutoff_source"] == "release"


def test_reading_a_quantization_fetches_its_parent_by_the_tag_name():
    get = Fetcher({f"{bm.HF_MODELS}/mlx-community/": fixture("model_qwen3-4b-mlx.json"),
                   f"{bm.HF_MODELS}/Qwen/Qwen3-4B-Instruct-2507": fixture("model_qwen3-4b.json")})
    facts = bm.read_training("mlx-community/Qwen3-4B-Instruct-2507-4bit", get=get)
    assert [u for u, _ in get.asked] == [
        f"{bm.HF_MODELS}/mlx-community/Qwen3-4B-Instruct-2507-4bit",
        f"{bm.HF_MODELS}/Qwen/Qwen3-4B-Instruct-2507"]
    assert facts["cutoff"] == "2025-08-05"


def test_an_adapter_is_dated_by_its_own_release_and_lists_its_datasets():
    facts = bm.training_facts(fixture("model_strands-decider.json"))
    assert facts["cutoff"] == "2026-10-05"
    assert "google/civil_comments" in facts["datasets"]
    assert "nvidia/HelpSteer2" in facts["datasets"]


def test_a_cutoff_stated_on_the_card_wins_over_the_release_date():
    facts = bm.training_facts(fixture("model_qwen3-4b.json"),
                              readme="## Notes\nKnowledge cutoff: June 2025.\n")
    assert (facts["cutoff"], facts["cutoff_source"]) == ("2025-06", "card")


@pytest.mark.parametrize("text, want", [
    ("Knowledge cutoff: June 2025", "2025-06"),
    ("training data cutoff of 2024-12", "2024-12"),
    ("the data cutoff is March 2026.", "2026-03"),
    ("no date here", ""),
])
def test_a_card_cutoff_is_read_from_prose(text, want):
    assert bm.card_cutoff(text) == want


def _bench(created: str, name: str = "hf:org/bench") -> bm.Benchmark:
    return bm.Benchmark(name=name, registry="huggingface", lane="decide", created=created)


TRAINING = [{"candidate": "Qwen/Qwen3-4B-Instruct-2507", "cutoff": "2025-08-05",
             "datasets": []},
            {"candidate": "ornith-ai/Ornith-1.5-35B-A3B-GGUF", "cutoff": "2026-08-18",
             "datasets": []},
            {"candidate": "StrandsAgents/strands-decider-2B-hobson-v21",
             "cutoff": "2025-01-01", "datasets": ["google/civil_comments"]}]


def test_a_benchmark_older_than_the_newest_cutoff_is_flagged():
    status, why = bm.contamination(_bench("2024-12-31"), TRAINING)
    assert status == "predates"
    assert "Ornith" in why and "2026-08-18" in why


def test_a_benchmark_newer_than_every_cutoff_is_after_cutoff():
    assert bm.contamination(_bench("2026-09-01"), TRAINING)[0] == "after-cutoff"


def test_a_benchmark_a_candidate_trained_on_is_declared_whatever_its_date():
    status, why = bm.contamination(
        _bench("2026-09-01", "hf:google/civil_comments"), TRAINING)
    assert status == "declared" and "strands-decider" in why


def test_a_fresh_reupload_of_an_old_benchmark_is_not_after_cutoff():
    """A 2026 mirror of a 2024 benchmark has a 2026 creation date and 2024 items."""
    old = _bench("2024-06-05", "hf:bigcode/bigcodebench")
    copy = _bench("2026-09-01", "hf:someone/bigcodebench")
    status, why = bm.contamination(copy, TRAINING, known=[old, copy])
    assert status == "predates" and "hf:bigcode/bigcodebench" in why
    unrelated = _bench("2026-09-01", "hf:someone/newthing")
    assert bm.contamination(unrelated, TRAINING, known=[old])[0] == "after-cutoff"


def test_with_no_cutoffs_contamination_is_unknown_not_clean():
    assert bm.contamination(_bench("2026-09-01"), [])[0] == "unknown"
    assert bm.contamination(_bench(""), TRAINING)[0] == "unknown"


@pytest.mark.parametrize("source, declared, hit", [
    ("AmazonScience/massive", ["mteb/amazon_massive_intent"], True),
    ("google/civil_comments", ["google/civil_comments"], True),
    ("nvidia/HelpSteer2", ["nvidia/HelpSteer2"], True),
    ("rajpurkar/squad_v2", ["google/boolq", "hotpotqa/hotpot_qa"], False),
    ("perplexity-ai/browsesafe-bench", ["google/civil_comments"], False),
])
def test_declared_overlap_matches_a_mirror_by_name(source, declared, hit):
    assert ct.declared(source, declared) == hit


def test_training_facts_are_stored_per_candidate_and_replaced():
    conn = ms.connect()
    ms.set_training(conn, "q/a", alias="q3-4b", cutoff="2025-08-05",
                    cutoff_source="release", datasets=["x/y"], at=1.0)
    ms.set_training(conn, "q/a", alias="q3-4b", cutoff="2025-06",
                    cutoff_source="card", datasets=[], at=2.0, lane="decide")
    rows = ms.training(conn)
    assert len(rows) == 1 and rows[0]["cutoff"] == "2025-06" and rows[0]["datasets"] == []
    assert rows[0]["lane"] == "decide"


# ---- import ----------------------------------------------------------------------

def mbpp_rows():
    return fixture("rows_mbpp-pro.json")["rows"]


def test_a_self_invoking_row_becomes_a_code_case_whose_reference_passes():
    row = mbpp_rows()[1]
    got = bi.convert_self_invoking(row["row"], row["row_idx"], bi.IMPORTERS["hf:CodeEval-Pro/mbpp-pro"],
                                   revision="abc")
    case, reference = got
    assert case["id"] == "mbpppro-1" and case["modality"] == "code"
    checks = case["assert"]["checks"]
    assert len(checks) == 4 and not any(c.startswith("assert") for c in checks)
    assert "first_n_non_primes" in case["prompt"] and "is_not_prime" in case["prompt"]
    att = case["attribution"]
    assert att["source"] == "hf:CodeEval-Pro/mbpp-pro" and att["item"] == "1"
    assert att["license"] == "MIT" and att["revision"] == "abc" and att["split"] == "train"
    assert code.check(reference, checks).ok


def test_a_row_whose_own_reference_fails_its_tests_is_skipped():
    row = dict(mbpp_rows()[1]["row"])
    row["test_code"] = row["test_code"].replace("[1, 4, 6]", "[1, 4, 7]")
    assert bi.convert_self_invoking(row, 1, bi.IMPORTERS["hf:CodeEval-Pro/mbpp-pro"]) is None


def test_a_row_with_fewer_than_three_tests_is_skipped():
    row = dict(mbpp_rows()[1]["row"])
    row["test_code"] = "\n".join(row["test_code"].splitlines()[:2])
    assert bi.convert_self_invoking(row, 1, bi.IMPORTERS["hf:CodeEval-Pro/mbpp-pro"]) is None


def rows_source(name: str, total: int | None = None):
    data = fixture(name)

    def get(offset: int, length: int) -> dict:
        rows = [r for r in data["rows"] if offset <= r["row_idx"] < offset + length]
        return {"rows": rows, "num_rows_total": total or data["num_rows_total"]}
    return get


def test_an_import_writes_loadable_cases_and_their_reference_solutions(tmp_path):
    hand = tmp_path / "code" / "slugify.yaml"
    hand.parent.mkdir(parents=True)
    hand.write_text("id: slugify\nmodality: code\nprompt: x\nassert:\n  checks: ['1', '1', '1']\n",
                    encoding="utf-8")
    written = bi.import_benchmark("hf:CodeEval-Pro/mbpp-pro", 3, tmp_path,
                                 rows=rows_source("rows_mbpp-pro.json", 6), revision="r1")
    assert len(written) == 3
    cases = [c for c in load_cases(tmp_path / "code") if c.id.startswith("mbpppro-")]
    assert len(cases) == 3
    for c in cases:
        ref = (tmp_path / "code" / "reference" / f"{c.id}.py").read_text(encoding="utf-8")
        assert code.check(ref, c.assertions["checks"]).ok
    assert hand.exists()
    again = bi.import_benchmark("hf:CodeEval-Pro/mbpp-pro", 3, tmp_path,
                                rows=rows_source("rows_mbpp-pro.json", 6), revision="r1")
    assert sorted(p.name for p in again) == sorted(p.name for p in written)


def test_a_guard_case_groups_balanced_pages_so_a_constant_answer_fails(tmp_path):
    """One boolean per case passes a constant responder half the time; four, two each way, never."""
    written = bi.import_benchmark("hf:perplexity-ai/browsesafe-bench", 2, tmp_path,
                                  rows=rows_source("rows_browsesafe.json"), revision="r2")
    cases = load_cases(tmp_path / "decide")
    assert len(written) == len(cases) == 2
    for c in cases:
        answers = list(c.assertions["answers"].values())
        assert len(answers) == bi.GROUP and answers.count(True) == answers.count(False)
        assert len(c.params["schema"]) == bi.GROUP
    orders = {tuple(c.assertions["answers"].values()) for c in cases}
    assert orders != {(True, True, False, False)}
    raw = yaml.safe_load(written[0].read_text(encoding="utf-8"))
    att = raw["attribution"]
    assert att["source"] == "hf:perplexity-ai/browsesafe-bench" and att["license"] == "MIT"
    items = {i for c in cases for i in yaml.safe_load(
        c.source.read_text(encoding="utf-8"))["attribution"]["item"].split(", ")}
    assert "41" not in items and len(items) == 8


def test_only_a_known_converter_with_an_allowed_license_imports(tmp_path):
    with pytest.raises(ValueError):
        bi.import_benchmark("hf:nobody/unknown", 3, tmp_path, rows=rows_source("rows_mbpp-pro.json"))
    for imp in bi.IMPORTERS.values():
        assert imp.license in bi.ALLOWED_LICENSES


def test_imported_items_are_third_party_data_not_prose_the_claims_scan_reads(tmp_path):
    """A dataset's own text is not a claim this project makes."""
    from harness import assertions
    written = bi.import_benchmark("hf:CodeEval-Pro/mbpp-pro", 2, tmp_path,
                                  rows=rows_source("rows_mbpp-pro.json", 6))
    ref = tmp_path / "code" / "reference" / f"{written[0].stem}.py"
    assert bi.MARK in ref.read_text(encoding="utf-8")
    assert code.check(ref.read_text(encoding="utf-8"),
                      load_cases(tmp_path / "code")[0].assertions["checks"]).ok
    for p in (written[0], ref):
        assert assertions.is_imported(p.read_text(encoding="utf-8"))
    assert not assertions.is_imported("# a hand-written note: 48 hours\n")


def test_a_decide_corpus_rewrite_keeps_cases_it_did_not_generate(tmp_path):
    from evals import decide_corpus
    mine = tmp_path / "guard-browsesafe-40.yaml"
    mine.write_text("# Imported by evals/benchmark_import.py\nid: x\n", encoding="utf-8")
    old = tmp_path / "route-massive-1.yaml"
    old.write_text("# x\n# Generated by evals/decide_corpus.py; edit the generator, not this file.\n",
                   encoding="utf-8")
    decide_corpus.write_cases([], tmp_path)
    assert mine.exists() and not old.exists()


def test_provenance_counts_imports_and_reads_the_older_attribution(tmp_path):
    bi.import_benchmark("hf:CodeEval-Pro/mbpp-pro", 2, tmp_path,
                        rows=rows_source("rows_mbpp-pro.json", 6))
    counts = bi.imported(tmp_path)
    assert counts["hf:CodeEval-Pro/mbpp-pro"]["code"] == 2
    shipped = bi.imported(Path(__file__).resolve().parents[1] / "evals" / "cases")
    assert shipped["hf:google/civil_comments"]["decide"] >= 6
    assert shipped["hf:rajpurkar/squad_v2"]["decide"] >= 6


# ---- the contamination probe -------------------------------------------------------

WORDS = " ".join(f"w{i}" for i in range(60))


def test_a_prefix_and_its_hidden_continuation_split_on_words():
    prefix, target = ct.split_prefix(WORDS)
    assert prefix.split()[-1] == f"w{ct.PREFIX_WORDS - 1}"
    assert target.split() == [f"w{i}" for i in range(ct.PREFIX_WORDS, ct.PREFIX_WORDS + ct.TARGET_WORDS)]
    assert ct.split_prefix("too short to probe") is None


def test_overlap_counts_leading_words_verbatim_ignoring_case_and_punctuation():
    assert ct.overlap("The quick, brown fox", "the quick brown fox jumps") == 0.8
    assert ct.overlap("a slow fox", "the quick brown fox jumps") == 0.0
    assert ct.overlap("", "the quick") == 0.0


def _case(cid: str, context: str):
    from evals.core import Case
    return Case(id=cid, modality="decide", prompt="p", context=context)


def test_a_probe_records_a_hit_a_miss_and_a_skip_per_family():
    conn = ms.connect()
    cases = [_case("check-a", WORDS), _case("check-b", WORDS + " x"), _case("route-c", "dim the lights")]

    def answers(model, prompt):
        return " ".join(f"w{i}" for i in range(ct.PREFIX_WORDS, 60)) if model == "m1" else "junk"

    got = ct.probe(conn, "m1", cases, ask=answers, at=5.0)
    assert [r["outcome"] for r in got] == ["hit", "hit", "skipped"]
    ct.probe(conn, "m2", cases, ask=answers, at=6.0)
    summary = {(s["model"], s["family"]): s for s in ms.probe_summary(conn)}
    assert summary[("m1", "check")]["hits"] == 2 and summary[("m1", "check")]["probed"] == 2
    assert summary[("m2", "check")]["hits"] == 0
    assert summary[("m1", "route")]["skipped"] == 1


def test_the_gateway_ask_sends_the_key_and_greedy_sampling(monkeypatch):
    from harness import gateway_key
    monkeypatch.setenv(gateway_key.ENV_VAR, "sk-test")
    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)

        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "w32 w33",
                                                 "reasoning_content": "thinking"}}]}
        return R()
    ask = ct.gateway_ask("http://gw:4000", post=post)
    assert ask("q3-4b", "prefix") == "w32 w33"
    assert sent["url"] == "http://gw:4000/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer sk-test"
    assert sent["body"]["temperature"] == 0 and sent["body"]["model"] == "q3-4b"


# ---- with and without overlapping cases (#470) ----------------------------------------

def test_a_lane_score_is_shown_with_and_without_cases_a_candidate_trained_on(store_run, tmp_path):
    root = tmp_path / "cases"
    (root / "decide").mkdir(parents=True)
    for cid, url in (("policy-1", "https://huggingface.co/datasets/google/civil_comments"),
                     ("guard-2", "https://huggingface.co/datasets/perplexity-ai/browsesafe-bench")):
        (root / "decide" / f"{cid}.yaml").write_text(yaml.safe_dump(
            {"id": cid, "attribution": {"url": url}}), encoding="utf-8")
    conn = ms.connect()
    ms.set_training(conn, "StrandsAgents/strands-decider-2B-hobson-v21", alias="decider-x",
                    cutoff="2026-10-05", cutoff_source="release",
                    datasets=["google/civil_comments"], at=1.0)
    rows = [{"case_id": "policy-1", "candidate": "decider-x", "passed": True},
            {"case_id": "guard-2", "candidate": "decider-x", "passed": False}]
    store_run("20261006-000000", "decide", rows=[
        {**r, "seconds": 1.0, "peak_kb": 0, "detail": "", "output": None,
         "artifact_path": None, "warnings": [], "metrics": {}} for r in rows], conn=conn)
    got = {s["candidate"]: s for s in ct.with_and_without(conn, "decide", root)}
    s = got["decider-x"]
    assert (s["all"], s["n_all"]) == (0.5, 2)
    assert (s["clean"], s["n_clean"]) == (0.0, 1)
    assert s["overlapping"] == ["policy-1"]


# ---- the store, the command, the loop -------------------------------------------------

def test_the_schema_has_the_benchmark_tables():
    conn = ms.connect()
    for table in ("benchmarks", "candidate_training", "contamination_probes"):
        conn.execute(f"SELECT * FROM {table}").fetchall()


def test_soh_benchmarks_lists_sources_contamination_and_imports(capsys):
    from harness import cli
    conn = ms.connect()
    b = bm.from_hf(fixture("hf_dataset_mbpp-pro.json"), "code")
    ms.record_benchmark(conn, b, at=1.0)
    ms.record_benchmark(conn, bm.from_hf(fixture("hf_dataset_browsesafe.json"), "decide"), at=1.0)
    ms.set_training(conn, "ornith-ai/Ornith-1.5-35B-A3B-GGUF", alias="sohot-code",
                    cutoff="2026-08-18", cutoff_source="release", datasets=[], at=1.0)
    conn.close()
    assert cli.main(["benchmarks", "--lane", "code", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in out["sources"]] == ["hf:CodeEval-Pro/mbpp-pro"]
    src = out["sources"][0]
    assert src["contamination"] == "predates" and src["license"] == "mit"
    assert "imported" in src and out["training"][0]["alias"] == "sohot-code"
    assert cli.main(["benchmarks", "--lane", "code"]) == 0
    text = capsys.readouterr().out
    assert "hf:CodeEval-Pro/mbpp-pro" in text and "predates" in text


def test_the_discover_sweep_reads_benchmarks_too(monkeypatch):
    from harness.commands import discover as discover_cmd
    assert "benchmarks" in discover_cmd.SOURCE_TIERS
    seen = []
    monkeypatch.setattr(discover_cmd, "_report_benchmarks", lambda a: seen.append(a) or 0)
    assert discover_cmd.cmd_discover(argparse.Namespace(benchmarks=True, json=False)) == 0
    assert len(seen) == 1
