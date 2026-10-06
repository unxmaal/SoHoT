"""The status page. Issue #231.

Answering "how have our lanes changed recently" took six commands and ad-hoc
SQL, and the answer landed in a chat message that was stale immediately.
"""
import json
import re

import pytest

from harness import report

#: Assert on the MARKUP, not the phrase: the page's own explanatory note
#: contains the words "no receipt here", so a bare substring check passes for
#: the wrong reason and fails for the right one.
NO_RECEIPT = '<span class="tag bad">no receipt here</span>'
STALE = '<span class="tag warn">last run'

LANE = {"lane": "code", "wanted": True, "serves": "q3-4b", "adopted": False,
        "measured": "q3-4b", "pass_rate": 0.78,
        "median_s": 1.4, "metrics": {"code_pass": 0.9}, "run": "r1",
        "age_days": 0.2, "unverified": False, "stale": False}


def _state(**over):
    base = {"generated": 0.0,
            "machine": {"runtimes": ["mlx"], "accelerator": "x", "kind":
                        "unified", "total_gb": 32.0, "available_gb": 8.0},
            "funnel": [{"tier": "inspect", "candidates": 9, "verdicts": 9}],
            "lanes": [dict(LANE)],
            "queue": {"waiting": 3, "rankable": 2, "by_lane": {"code": 2},
                      "top": [], "wanted_with_none": ["web"]},
            "sources": [{"name": "s", "last_fetched": 1.0, "age_days": 0.5,
                         "stale": False}]}
    base.update(over)
    return base


# --- "changed" needs a referent -------------------------------------------

def test_a_first_report_marks_nothing_changed():
    """Nothing to compare against is not the same as nothing having changed,
    and the page has to say which one it means."""
    page = report.render(_state(), before={})
    assert 'class="changed"' not in page
    assert "No previous report" in page


def test_a_lane_that_changed_what_it_serves_is_highlighted():
    before = _state()
    now = _state(lanes=[dict(LANE, serves="something-new")])
    got = report.changes(now, before)
    assert got["code"] == "serves something-new, was q3-4b"
    assert 'class="changed"' in report.render(now, before)


def test_a_lane_re_measured_in_a_new_run_is_highlighted():
    before = _state()
    now = _state(lanes=[dict(LANE, run="r2")])
    assert report.changes(now, before)["code"] == "re-measured in r2"


def test_an_unchanged_lane_is_not_highlighted():
    """The negative control. A page that highlights every row highlights
    nothing."""
    assert report.changes(_state(), _state()) == {}
    assert 'class="changed"' not in report.render(_state(), _state())


def test_a_lane_that_did_not_exist_before_is_new_rather_than_changed():
    before = _state(lanes=[])
    assert report.changes(_state(), before)["code"] == "new lane"


# --- staleness is three different things ----------------------------------

def test_a_lane_with_no_receipt_is_unverified_not_stale():
    """Quoting an age for a lane that never ran would be a fabrication."""
    page = report.render(_state(lanes=[
        dict(LANE, run="", age_days=None, unverified=True, stale=False)]), {})
    assert NO_RECEIPT in page
    assert STALE not in page


def test_a_lane_measured_long_ago_reports_its_age():
    page = report.render(_state(lanes=[
        dict(LANE, age_days=42.0, stale=True)]), {})
    assert f'{STALE} 42d ago' in page
    assert NO_RECEIPT not in page


def test_a_wanted_lane_with_an_empty_queue_is_named():
    assert "nothing queued for web" in report.render(_state(), {})


# --- self-contained -------------------------------------------------------

def test_the_page_fetches_nothing(tmp_path):
    """It has to open on a machine with no network, which is the machine this
    runs on. No CDN, no fonts, no <script src>."""
    page = report.render(_state(), {})
    assert not re.search(r'<(?:script|link|img)[^>]*\bsrc=|<link[^>]*\bhref=',
                         page), "the page pulls an external resource"
    assert "<style>" in page, "styling must be inline"


def test_the_page_escapes_what_the_store_holds():
    """Proposal names come from feeds written by strangers. Untrusted text."""
    page = report.render(_state(lanes=[
        dict(LANE, serves="<script>alert(1)</script>")]), {})
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_writing_leaves_the_state_beside_the_page(tmp_path):
    """The NEXT run needs it; without it, 'changed' has no referent."""
    out = tmp_path / "r.html"
    monkey = report.state
    report.state = lambda conn=None: _state()
    try:
        report.write(out)
    finally:
        report.state = monkey
    assert out.exists()
    assert json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["lanes"]


# --- the ladder -----------------------------------------------------------

def test_the_ladder_is_shown_in_the_order_work_flows_through_it():
    """memory_store.TIERS enumerates valid tier NAMES and omits `fetch`.
    A different question, and using it here put fetch last."""
    assert report.LADDER.index("fetch") < report.LADDER.index("screen")
    assert report.LADDER.index("screen") < report.LADDER.index("adopt")


def test_the_funnel_orders_by_the_ladder_not_by_count(tmp_path):
    from harness import memory_store as ms

    conn = ms.connect(tmp_path / "d.db")
    try:
        for name, tier in (("a", "adopt"), ("b", "inspect"), ("c", "screen")):
            ms.record(conn, ms.Seen(name=name, source="t", url="", why="",
                                    relevance=0, kind="candidate",
                                    registry=ms.HUGGINGFACE, lane="code",
                                    resolved=name))
            ms.decide(conn, name, "queued", tier=tier, detail="d")
        got = [r["tier"] for r in report.funnel(conn)]
        assert got == ["inspect", "screen", "adopt"]
    finally:
        conn.close()


# --- what won a lane and when it last ran are different questions ---------

def _stamp(days_ago: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(time.time() - days_ago * 86400))


def _lanes(monkeypatch, typed=None, adopted=None):
    from harness import adopt, winners
    from harness import memory_store as ms
    monkeypatch.setattr(winners, "typed",
                        lambda: dict(typed or {"svg": "local-large"}))
    monkeypatch.setattr(adopt, "current", lambda conn, machine=None: {
        lane: {"spec": spec, "candidate_id": None, "how": adopt.MEASURED}
        for lane, spec in (adopted or {}).items()})
    conn = ms.connect()
    try:
        return {l["lane"]: l for l in report.lanes_state(conn)}
    finally:
        conn.close()


def test_staleness_comes_from_the_newest_run_not_the_winning_one(
        store_run, monkeypatch):
    """`winners` answers "what WON this lane"; staleness asks "when was this
    lane LAST measured". Reading the age off the winner reported svg 12 days
    stale minutes after it was re-run. #234. The age is the receipt's own
    time, never a directory mtime. #331."""
    store_run("legacy-ev-item2b", "svg", {"local-large": {"pass_rate": 1.0}},
              generated=_stamp(30))
    store_run("20260919-204639-944-0000-svg", "svg",
              {"local-large": {"pass_rate": 0.5}}, generated=_stamp(0.01))
    svg = _lanes(monkeypatch)["svg"]
    assert svg["last_run"] == "20260919-204639-944-0000-svg"
    assert svg["age_days"] < 1.0 and not svg["stale"]
    assert (svg["pass_rate"], svg["best_pass_rate"]) == (0.5, 1.0)


def test_a_lane_with_no_stored_run_is_unverified(monkeypatch):
    svg = _lanes(monkeypatch)["svg"]
    assert svg["last_run"] == "" and svg["unverified"]


def test_a_results_json_nobody_stored_is_not_a_run(monkeypatch):
    """Pins the conversion: a directory scan would find this file. #410."""
    from harness import memory_store as ms
    from harness import paths
    ms.connect().close()      # the store exists, so no backfill reads it
    d = paths.runs() / "20261006-000000-000-0000-svg"
    d.mkdir(parents=True)
    (d / "results.json").write_text(json.dumps({
        "generated": _stamp(0), "environment": {"hw_model": "Mac17,15"},
        "receipt": {"modality": "svg", "tier": "measure"},
        "summary": {"local-large": {"pass_rate": 1.0}},
        "rows": [{"case_id": "a", "candidate": "local-large", "passed": True,
                  "seconds": 1.0, "peak_kb": 0, "detail": ""}]}),
        encoding="utf-8")
    svg = _lanes(monkeypatch)["svg"]
    assert svg["last_run"] == "" and svg["pass_rate"] is None


def test_another_machines_run_is_not_this_machines_measurement(
        store_run, monkeypatch):
    """The runs directory migrates with the home. #331."""
    store_run("20261001-000000-svg", "svg", {"local-large": {"pass_rate": 0.5}},
              generated=_stamp(3))
    store_run("20261004-000000-svg", "svg", {"local-large": {"pass_rate": 1.0}},
              generated=_stamp(1), hw_model="Another,1")
    svg = _lanes(monkeypatch)["svg"]
    assert (svg["last_run"], svg["pass_rate"]) == ("20261001-000000-svg", 0.5)


def test_only_another_machines_runs_means_never_measured_here(
        store_run, monkeypatch):
    store_run("20261004-000000-svg", "svg", {"local-large": {"pass_rate": 1.0}},
              hw_model="Another,1")
    svg = _lanes(monkeypatch)["svg"]
    assert svg["last_run"] == "" and svg["pass_rate"] is None


def test_a_run_that_names_no_machine_is_not_assumed_to_be_this_one(
        store_run, monkeypatch):
    store_run("20261004-000000-svg", "svg", {"local-large": {"pass_rate": 1.0}},
              hw_model="")
    assert _lanes(monkeypatch)["svg"]["last_run"] == ""


def test_this_machines_newest_run_still_wins(store_run, monkeypatch):
    """Negative control: two of this machine's own, newest by receipt time."""
    store_run("20261002-000000-svg", "svg", {"local-large": {"pass_rate": 0.9}},
              generated=_stamp(1))
    store_run("20261001-000000-svg", "svg", {"local-large": {"pass_rate": 0.4}},
              generated=_stamp(2))
    svg = _lanes(monkeypatch)["svg"]
    assert (svg["last_run"], svg["pass_rate"]) == ("20261002-000000-svg", 0.9)


def test_the_numbers_are_this_machines_not_the_winners(store_run, monkeypatch):
    """The winner may be another machine's run; its median is a fact about
    that machine. #341."""
    store_run("legacy", "svg", {"local-large": {"pass_rate": 1.0,
                                                "median_s": 5.10}},
              hw_model="Another,1", generated=_stamp(10))
    store_run("20261005-000000-svg", "svg",
              {"local-large": {"passed": 2, "total": 3, "median_s": 1.36,
                               "metrics": {"ink": 0.34}}})
    svg = _lanes(monkeypatch)["svg"]
    assert (svg["pass_rate"], svg["median_s"]) == (0.667, 1.36)
    assert (svg["best_pass_rate"], svg["best_median_s"]) == (1.0, 5.10)


# --- #410's acceptance: each lane shows the row of what it SERVES ----------

def test_code_shows_the_adopted_candidate_not_a_newer_higher_scorer(
        store_run, monkeypatch):
    """code serves Ornith and showed q3-coder from another run. #410."""
    ornith = "llamacpp:Ornith-1.5-35B-Q4_K_M"
    store_run("20261006-001631-371-0000-code", "code",
              {ornith: {"passed": 39, "total": 42},
               "q3-coder": {"passed": 32, "total": 42}},
              specs={ornith: ornith, "q3-coder": "q3-coder"},
              generated=_stamp(1))
    store_run("20261006-090000-000-0000-code", "code",
              {"q3-coder": {"passed": 42, "total": 42}},
              specs={"q3-coder": "q3-coder"}, generated=_stamp(0.1))
    code = _lanes(monkeypatch, typed={"code": "q3-4b"},
                  adopted={"code": ornith})["code"]
    assert code["serves"] == ornith and code["measured"] == ornith
    assert code["pass_rate"] == round(39 / 42, 3)
    assert code["run"] == "20261006-001631-371-0000-code"


def test_svg_shows_local_large_even_when_q3_30b_won_the_run(
        store_run, monkeypatch):
    store_run("20261005-194924-860-0000-svg", "svg",
              {"q3-30b": {"passed": 9, "total": 9},
               "local-large": {"passed": 4, "total": 9}},
              specs={"q3-30b": "q3-30b", "local-large": "local-large"})
    svg = _lanes(monkeypatch)["svg"]
    assert (svg["measured"], svg["pass_rate"]) == ("local-large", 0.444)
    assert svg["best"] == "q3-30b"


def _key(lane, served):
    from harness import candidates, screen
    key = candidates.key_of(screen.candidate_for(lane, served)
                            or served)
    if not key:
        pytest.skip(f"no runner for {served} on this platform")
    return key


def test_tts_shows_its_own_five_of_five_past_a_newer_screen(
        store_run, monkeypatch):
    """The receipt has no specs map; the row is found through the candidate
    row of what the lane serves. A newer screen of something else is not
    the lane's measurement."""
    kokoro = "mlx-community/Kokoro-82M-bf16"
    key = _key("tts", kokoro)
    store_run("20261005-161337-201-0000-tts", "tts",
              {key: {"passed": 5, "total": 5}}, generated=_stamp(1))
    store_run("screen-1791290659-tts", "tts",
              {"supertonic-3": {"passed": 0, "total": 1}}, tier="screen",
              generated=_stamp(0.01))
    tts = _lanes(monkeypatch, typed={"tts": kokoro})["tts"]
    assert (tts["measured"], tts["pass_rate"]) == (key, 1.0)
    assert tts["last_run"] == "20261005-161337-201-0000-tts"


def test_video_shows_the_h3_run_not_the_newer_resident_variant(
        store_run, monkeypatch):
    key = _key("video", "h3")
    store_run("20261005-174829-658-0000-video", "video",
              {key: {"passed": 1, "total": 1}}, generated=_stamp(1))
    store_run("20261005-180410-072-0000-video", "video",
              {f"{key}@ssd_streaming=false": {"passed": 0, "total": 1}},
              generated=_stamp(0.9))
    video = _lanes(monkeypatch, typed={"video": "h3"})["video"]
    assert (video["measured"], video["pass_rate"]) == (key, 1.0)
    assert video["run"] == "20261005-174829-658-0000-video"
    assert video["last_run"] == "20261005-180410-072-0000-video"
