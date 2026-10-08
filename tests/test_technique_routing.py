"""A technique is laned by evidence of the lane's task; a general LLM or serving paper is not code. #631."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import lanes, papers, rank
from harness import memory_store as ms
from harness.commands import loop

FIX = Path(__file__).resolve().parent / "fixtures" / "papers" / "technique_routing.json"
PAPERS = {p["id"]: p for p in json.loads(FIX.read_text(encoding="utf-8"))}

ROBOTICS = "2610.00864"      # Kinematic MeanFlow: robot action generation
CROSS_LINGUAL = "2610.01921"  # Cross-Lingual Alignment ... using MoE Routers
MULTILINGUAL = "2609.35378"   # Multilinguality in Hybrid Attention LLMs
SLIMWISE = "2609.34117"       # SlimWise: ... Efficient MoE Serving
CODEX = "2107.03374"          # Evaluating Large Language Models Trained on Code: the positive control


def route(pid):
    p = PAPERS[pid]
    return lanes.technique_route(p["title"], p["summary"])


@pytest.mark.parametrize("pid, want", [
    (ROBOTICS, ""),
    (CROSS_LINGUAL, lanes.GENERAL),
    (MULTILINGUAL, lanes.GENERAL),
    (SLIMWISE, lanes.SERVING),
    (CODEX, "code"),
])
def test_each_live_title_routes_to_its_task_not_to_code(pid, want):
    assert route(pid) == want


@pytest.mark.parametrize("pid, lane", [
    (ROBOTICS, ""), (CROSS_LINGUAL, ""), (MULTILINGUAL, ""), (SLIMWISE, ""), (CODEX, "code"),
])
def test_a_paper_is_recorded_with_a_lane_only_when_it_names_the_lanes_task(pid, lane):
    p = PAPERS[pid]
    assert papers.lane_of(p["title"], p["summary"]) == lane


def test_buckets_are_not_lanes():
    assert lanes.SERVING not in lanes.ALL and lanes.GENERAL not in lanes.ALL


@pytest.mark.parametrize("text", [
    "Code is available at https://github.com/org/repo.",
    "We release our code and models.",
    "Code and data: https://example.org",
])
def test_a_code_release_line_is_not_evidence_of_a_code_task(text):
    assert lanes.technique_route("A New Method", text) == ""


@pytest.mark.parametrize("title", [
    "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?",
    "Automated Program Repair with Large Language Models",
    "Test Generation for Python Projects",
])
def test_a_code_task_in_the_title_routes_to_code(title):
    assert lanes.technique_route(title, "") == "code"


def test_another_lane_still_routes_by_its_own_words():
    assert lanes.technique_route("Fewer Steps for Text-to-Image Diffusion", "") == "image"


def stored(pid, lane="code", lane_source="prose", times=1):
    p = PAPERS[pid]
    return {"name": f"arxiv:{pid}", "lane": lane, "lane_source": lane_source,
            "title": p["title"], "description": f"{p['title']}. {p['summary']}",
            "times": times, "last_seen": 0.0, "url": f"https://huggingface.co/papers/{pid}"}


def live_rows():
    return [stored(pid) for pid in (ROBOTICS, CROSS_LINGUAL, MULTILINGUAL, SLIMWISE, CODEX)]


def test_rows_the_store_filed_under_code_by_prose_are_rerouted_at_report_time():
    groups = rank.techniques_wanted(live_rows())
    assert [(g["lane"], [t["name"] for t in g["techniques"]]) for g in groups] == [
        ("code", [f"arxiv:{CODEX}"])]
    other = rank.techniques_unlaned(live_rows())
    assert [t["name"] for t in other[lanes.SERVING]] == [f"arxiv:{SLIMWISE}"]
    assert sorted(t["name"] for t in other[lanes.GENERAL]) == sorted(
        [f"arxiv:{CROSS_LINGUAL}", f"arxiv:{MULTILINGUAL}"])
    assert [t["name"] for t in other[""]] == [f"arxiv:{ROBOTICS}"]
    assert rank.techniques_laneless(live_rows()) == 4


def test_a_lane_the_publisher_gave_is_kept():
    row = stored(SLIMWISE, lane="code", lane_source="card")
    assert [g["lane"] for g in rank.techniques_wanted([row])] == ["code"]


def test_the_report_names_the_buckets_and_lists_the_unrouted_by_title():
    text = "\n".join(loop._techniques_wanted_lines(live_rows()))
    assert "1 technique(s) in 1 lane(s)" in text
    lines = text.splitlines()
    serving = next(i for i, l in enumerate(lines) if l.strip().startswith("serving"))
    assert "not a lane" in lines[serving]
    assert "SlimWise" in lines[serving + 1]
    general = next(i for i, l in enumerate(lines) if l.strip().startswith("general"))
    assert "2 technique(s)" in lines[general]
    assert "1 technique(s) name no lane the prose routing knows" in text
    assert "Kinematic MeanFlow" in text


def test_a_lane_scoped_report_leaves_the_buckets_out():
    text = "\n".join(loop._techniques_wanted_lines(live_rows(), want="code"))
    assert "Evaluating Large Language Models Trained on Code" in text
    assert "SlimWise" not in text and "Kinematic" not in text


def test_the_store_lists_a_techniques_lane_source(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    p = PAPERS[SLIMWISE]
    ms.record(conn, ms.Seen(name=f"arxiv:{SLIMWISE}", source=papers.SOURCE, why=p["title"],
                            lane="code", lane_source="prose", category=ms.TECHNIQUE,
                            description=f"{p['title']}. {p['summary']}"))
    (row,) = ms.techniques(conn)
    assert row["lane_source"] == "prose"


def test_only_a_code_lane_read_from_prose_is_reread():
    row = {"name": "arxiv:1", "lane": "image", "lane_source": "prose", "title": "MEND",
           "description": "MEND. A stored description cut short before its lane word."}
    assert rank.technique_route(row) == "image"


def test_a_vision_paper_that_counts_tokens_is_not_a_general_text_model_paper():
    assert lanes.technique_route("Saliency Maps via Concept-Aware Attribution",
                                 "Visual explanations over patch tokens.") == ""
