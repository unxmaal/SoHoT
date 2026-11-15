"""Work lanes lead the screen's lane turns; a code survivor is also the extract lane's challenger. #2033."""
from harness import fetching, lanes
from harness.commands import measure as measure_cmd


def test_each_turn_takes_the_work_lanes_before_the_media_lanes():
    rows = [{"name": "img1", "lane": "image"}, {"name": "vid1", "lane": "video"},
            {"name": "code1", "lane": "code"}, {"name": "dec1", "lane": "decide"},
            {"name": "img2", "lane": "image"}, {"name": "code2", "lane": "code"},
            {"name": "ext1", "lane": "extract"}]
    got = [r["name"] for r in fetching.by_lane_turns(rows)]
    assert got == ["ext1", "dec1", "code1", "img1", "vid1", "code2", "img2"]


def test_a_code_filing_is_measured_in_extract_too_and_a_media_filing_nowhere_else():
    assert lanes.also_in("code") == ("extract",)
    assert lanes.also_in("text") == ("extract",)
    assert lanes.also_in("extract") == ("code",)
    assert lanes.also_in("image") == ()
    assert lanes.also_in("web") == ()
    assert lanes.also_in("repo") == ()


def test_an_unscoped_measure_plans_a_code_survivor_in_both_lanes(monkeypatch):
    from harness import memory_store as ms
    survivors = [{"name": "Qwen/Qwen3-8B", "lane": "code"}, {"name": "img/x", "lane": "image"}]
    monkeypatch.setattr(ms, "survivors", lambda store, **kw: [dict(r) for r in survivors])
    got = measure_cmd.measurable(None, 100)
    assert [(r["name"], measure_cmd.lane_for(r)) for r in got] == [
        ("Qwen/Qwen3-8B", "code"), ("img/x", "image"), ("Qwen/Qwen3-8B", "extract")]
    scoped = measure_cmd.measurable(None, 100, want="extract")
    assert [(r["name"], measure_cmd.lane_for(r, "extract")) for r in scoped] == [("Qwen/Qwen3-8B", "extract")]
