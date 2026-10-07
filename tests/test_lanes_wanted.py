"""`lanes wanted`: no tools or adapters (#556), grouped by task with evidence and no verdict (#558)."""
import pytest

from harness import rank
from harness.commands import loop

GIB = 1024 ** 3


def row(name, times=3, **kw):
    base = {"name": name, "lane": "", "times": times, "registry": "huggingface",
            "hf_task": "", "card_tags": "[]", "attaches_to": "", "size_bytes": 0}
    base.update(kw)
    return base


def test_an_adapter_that_recurs_is_not_a_lane_wanted():
    rows = [row("org/style-lora", attaches_to="lora"), row("org/LTX-dearchive-lora"),
            row("org/translator", hf_task="translation")]
    assert [r["name"] for r in rank.wanted(rows)] == ["org/translator"]


def test_a_github_repo_with_no_task_is_a_tool_not_a_lane():
    rows = [row("ml-explore/mlx-swift-examples", registry="github"),
            row("org/translator", hf_task="translation")]
    assert [r["name"] for r in rank.wanted(rows)] == ["org/translator"]
    assert [r["name"] for r in rank.tools_wanted(rows)] == ["ml-explore/mlx-swift-examples"]


def test_tools_wanted_keeps_the_recurrence_floor_and_drops_adapters():
    rows = [row("a/once", times=1, registry="github"),
            row("a/comfy-pack", registry="github", attaches_to="comfyui"),
            row("a/has-lane", registry="github", lane="code")]
    assert rank.tools_wanted(rows) == []


def _translation_and_rerank():
    return [
        row("tencent/Hy-MT2-1.8B", times=4, hf_task="translation", size_bytes=4 * GIB),
        row("tencent/Hy-MT2-30B-A3B", times=2, hf_task="translation", size_bytes=60 * GIB),
        row("other/mt-small", times=1, hf_task="translation", size_bytes=1 * GIB),
        row("a/reranker-1b", times=2, hf_task="text-ranking", size_bytes=90 * GIB),
        row("a/reranker-8b", times=2, hf_task="text-ranking", size_bytes=95 * GIB),
        row("b/summer", times=5, hf_task="summarization"),
    ]


def test_groups_count_models_publishers_and_sightings_per_task():
    groups = {g["task"]: g for g in rank.wanted_groups(_translation_and_rerank(),
                                                       ceiling_gib=22.0)}
    mt = groups["translation"]
    assert (len(mt["models"]), len(mt["publishers"]), mt["sightings"]) == (3, 2, 7)
    assert mt["fits"] == "yes" and mt["metric"] == "chrF"
    rr = groups["text-ranking"]
    assert (len(rr["models"]), len(rr["publishers"]), rr["fits"]) == (2, 1, "no")
    assert groups["summarization"]["fits"] == "unknown"
    assert groups["summarization"]["metric"] == ""


def test_a_group_falls_back_to_a_task_named_in_the_card_tags_and_ocr_is_its_own_task():
    rows = [row("a/ocr", hf_task="image-text-to-text", card_tags='["ocr"]'),
            row("b/pii", card_tags='["transformers", "token-classification"]'),
            row("c/mystery")]
    tasks = {g["task"] for g in rank.wanted_groups(rows, ceiling_gib=22.0)}
    assert tasks == {"ocr", "token-classification", rank.NO_TASK}


def test_groups_are_ordered_by_distinct_models_then_sightings():
    order = [g["task"] for g in rank.wanted_groups(_translation_and_rerank(),
                                                   ceiling_gib=22.0)]
    assert order == ["translation", "text-ranking", "summarization"]


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/rank.py:MEASURABLE")
def test_an_unlisted_task_is_unknown_never_unmeasurable():
    assert rank.metric_for("summarization") == ""
    assert rank.metric_for("translation") == "chrF"
    assert rank.metric_for("image-to-text") == "CER"
    assert rank.metric_for("token-classification") == "F1"


def test_the_report_prints_evidence_and_asks_rather_than_decides():
    text = "\n".join(loop._lanes_wanted_lines(_translation_and_rerank(), ceiling_gib=22.0))
    assert "translation" in text and "chrF" in text
    assert "used here?" in text
    for verdict in ("meets the bar", "recommend", "should add", "add a lane"):
        assert verdict not in text.lower()
    tr = next(l for l in text.splitlines() if l.strip().startswith("translation"))
    assert tr.split()[1:4] == ["3", "2", "7"]
