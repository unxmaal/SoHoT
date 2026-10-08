"""Discovery finds techniques, not only models: a proposal's category, a papers source, `techniques wanted`. #576."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import time
from pathlib import Path

import pytest

from harness import feeds, inspect as ins, papers, rank
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import loop
from harness.memory_store.migrations import retractions

FIX = Path(__file__).resolve().parent / "fixtures" / "papers" / "daily_papers.json"
DAY = 86400.0
NOW = 1_791_000_000.0


def daily(url, params=None):
    return json.loads(FIX.read_text(encoding="utf-8"))


class Asked:
    """A papers fetcher that records every request and answers from the recorded fixture."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if self.fail:
            raise RuntimeError("503 from the papers API")
        return daily(url, params)


@pytest.fixture
def conn(tmp_path):
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


def category(conn, name):
    row = conn.execute("SELECT category FROM proposals WHERE name = ?", (name,)).fetchone()
    return row["category"] if row else None


# ---- the column ---------------------------------------------------------------

def test_a_proposal_says_whether_it_is_a_model_a_tool_or_a_technique(conn):
    assert ms.CATEGORIES == ("model", "tool", "technique")
    ms.record(conn, ms.Seen(name="org/m", source="s"))
    assert category(conn, "org/m") == ""


def test_a_sighting_fills_an_unknown_category_and_never_overwrites_a_known_one(conn):
    ms.record(conn, ms.Seen(name="org/r", source="a"))
    ms.record(conn, ms.Seen(name="org/r", source="b", category=ms.TOOL))
    assert category(conn, "org/r") == "tool"
    ms.record(conn, ms.Seen(name="org/r", source="c", category=ms.TECHNIQUE))
    ms.record(conn, ms.Seen(name="org/r", source="d"))
    assert category(conn, "org/r") == "tool"


def test_the_backfill_fills_only_what_the_store_already_knows(conn):
    """RULE #292: a migration reads what writers stored and invents nothing."""
    ms.record(conn, ms.Seen(name="hf/model", source="s", registry=ms.HUGGINGFACE))
    ms.record(conn, ms.Seen(name="old/weights", source="s", kind="weights"))
    ms.record(conn, ms.Seen(name="gh/engine", source="s", registry=ms.GITHUB))
    ms.record(conn, ms.Seen(name="gh/tasked", source="s", registry=ms.GITHUB))
    conn.execute("UPDATE proposals SET hf_task = 'text-generation' WHERE name = 'gh/tasked'")
    ms.record(conn, ms.Seen(name="gh/paper-code", source="s", registry=ms.GITHUB,
                            description="Official implementation of our NeurIPS paper"))
    ms.record(conn, ms.Seen(name="arxiv:2610.00001", source=papers.SOURCE))
    ms.record(conn, ms.Seen(name="who/knows", source="reddit-sd-week"))
    ms.record(conn, ms.Seen(name="hf/already", source="s", registry=ms.HUGGINGFACE,
                            category=ms.TECHNIQUE))
    conn.execute("UPDATE proposals SET category = ''  WHERE name <> 'hf/already'")
    conn.commit()
    retractions._fill_categories(conn)
    got = {r["name"]: r["category"] for r in conn.execute("SELECT name, category FROM proposals")}
    assert got == {"hf/model": "model", "old/weights": "model", "gh/engine": "tool",
                   "gh/tasked": "", "gh/paper-code": "technique",
                   "arxiv:2610.00001": "technique", "who/knows": "",
                   "hf/already": "technique"}


def test_a_store_at_the_previous_schema_gains_the_column_and_its_backfill(tmp_path):
    """Through the migration chain, not the DDL: the column, then the data step."""
    from harness.memory_store.schema import _columns
    path = tmp_path / "old.db"
    conn = ms.connect(path)
    ms.record(conn, ms.Seen(name="hf/model", source="s", registry=ms.HUGGINGFACE))
    if ms._drop_column(conn, "proposals", "category") is False:
        pytest.skip("this SQLite cannot drop a column")
    conn.execute("UPDATE meta SET value = '55' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    conn = ms.connect(path)
    try:
        assert "category" in _columns(conn, "proposals")
        assert category(conn, "hf/model") == "model"
    finally:
        conn.close()


# ---- inspect sets it ----------------------------------------------------------

def test_a_registry_card_is_a_model():
    assert ins.card_facts({"pipeline_tag": "text-generation", "tags": []}).category == "model"


@pytest.mark.parametrize("meta, want", [
    ({"description": "Official implementation of the paper 'Fast Decoding'"}, "technique"),
    ({"description": "Code for our ICLR 2026 paper", "topics": []}, "technique"),
    ({"description": "A new decoding method", "topics": ["arxiv", "llm"]}, "technique"),
    ({"description": "See https://arxiv.org/abs/2610.00001"}, "technique"),
    ({"description": "A fast inference engine for Apple Silicon", "topics": ["mlx"]}, "tool"),
    ({"description": "", "topics": []}, "tool"),
])
def test_a_github_repo_is_a_technique_when_it_names_a_paper_else_a_tool(meta, want):
    assert ins.repo_facts(meta).category == want


def test_set_card_writes_the_category(conn):
    ms.record(conn, ms.Seen(name="org/repo", source="s", registry=ms.GITHUB))
    ms.set_card(conn, "org/repo", ins.repo_facts({"description": "Official PyTorch "
                                                               "implementation of our paper"}))
    assert category(conn, "org/repo") == "technique"


# ---- the papers source --------------------------------------------------------

def test_each_paper_becomes_a_technique_with_its_title_link_and_abstract(conn):
    got = papers.sweep(conn, get=Asked(), now=NOW)
    assert len(got) == 6
    row = conn.execute("SELECT * FROM proposals WHERE name = 'arxiv:2610.07384'").fetchone()
    assert row["category"] == "technique"
    assert "WildMatch" in row["description"] and "wildlife" in row["description"].lower()
    s = conn.execute("SELECT * FROM sightings WHERE proposal_id = ?", (row["id"],)).fetchone()
    assert s["source"] == papers.SOURCE
    assert s["url"] == "https://huggingface.co/papers/2610.07384"
    assert s["why"].startswith("WildMatch")


@pytest.mark.parametrize("paper, lane", [
    ("2610.07384", "image"),    # the title names images
    ("2610.08777", "video"),    # the title names video
    ("2609.29123", "tts"),      # the title names speech; the abstract names several lanes
    ("2610.04596", ""),         # names language models but no code task: general, not code (#631)
    ("2610.06104", ""),         # robot policies: no lane, and none is invented
])
def test_a_paper_is_laned_by_the_same_prose_routing_as_a_model(conn, paper, lane):
    papers.sweep(conn, get=Asked(), now=NOW)
    row = conn.execute("SELECT lane, lane_source FROM proposals WHERE name = ?",
                       (f"arxiv:{paper}",)).fetchone()
    assert row["lane"] == lane
    assert row["lane_source"] == ("prose" if lane else "")


def test_a_paper_is_never_queued_for_the_model_ladder(conn):
    papers.sweep(conn, get=Asked(), now=NOW)
    assert ms.judgeable(conn) == []
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == 0


def test_the_read_is_recorded_in_the_sources_table(conn):
    papers.sweep(conn, get=Asked(), now=NOW)
    row = ms.source_row(conn, papers.SOURCE)
    assert (row["kind"], row["last_status"], row["last_read_at"]) == ("papers", "ok", NOW)
    assert row["url"] == papers.API


def test_a_failed_read_is_recorded_and_raises_nothing(conn):
    assert papers.sweep(conn, get=Asked(fail=True), now=NOW) == []
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == "failed" and "503" in row["last_error"]
    assert row["last_read_at"] is None


def test_one_call_on_a_first_read_and_none_again_the_same_day(conn):
    first = Asked()
    papers.sweep(conn, get=first, now=NOW)
    assert first.calls == [(papers.API, {})]
    again = Asked()
    assert papers.sweep(conn, get=again, now=NOW + 3600) == []
    assert again.calls == []
    forced = Asked()
    papers.sweep(conn, get=forced, now=NOW + 3600, force=True)
    assert len(forced.calls) == 1


def test_a_sweep_catches_up_on_each_day_it_missed_and_no_further_than_the_cap(conn):
    papers.sweep(conn, get=Asked(), now=NOW)
    later = Asked()
    papers.sweep(conn, get=later, now=NOW + 3 * DAY)
    dates = [p.get("date") for _, p in later.calls]
    assert len(dates) == 3 and dates == sorted(dates)
    assert dates[-1] == time.strftime("%Y-%m-%d", time.gmtime(NOW + 3 * DAY))
    much_later = Asked()
    papers.sweep(conn, get=much_later, now=NOW + 40 * DAY)
    assert len(much_later.calls) == papers.MAX_DAYS


def test_a_paper_listed_again_is_one_proposal_and_one_sighting(conn):
    papers.sweep(conn, get=Asked(), now=NOW)
    papers.sweep(conn, get=Asked(), now=NOW + DAY)
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE name = 'arxiv:2610.07384'"
                        ).fetchone()[0] == 1
    n = conn.execute("SELECT COUNT(*) FROM sightings s JOIN proposals p ON p.id = s.proposal_id "
                     "WHERE p.name = 'arxiv:2610.07384'").fetchone()[0]
    assert n == 1


def test_the_papers_source_is_a_source_family_of_the_sweep():
    assert "papers" in discover_cmd.SOURCE_TIERS
    by = {s.name: s for s in feeds.DEFAULT_SOURCES}
    assert by[papers.SOURCE].kind == "papers"
    assert by[papers.SOURCE].url == papers.API


def test_the_feed_reader_leaves_the_papers_source_to_its_own_tier():
    from harness import discover
    read = []
    discover.from_feeds(sources=[s for s in feeds.DEFAULT_SOURCES if s.name == papers.SOURCE],
                        reader=lambda src: read.append(src.name) or [], verify=False)
    assert read == []


def test_the_sweep_dispatches_the_papers_tier(monkeypatch, capsys):
    from harness import papers as P
    seen = []
    monkeypatch.setattr(P, "sweep", lambda conn, **k: seen.append(k) or [])
    a = argparse.Namespace(papers=True, json=False, force=False, lane="")
    discover_cmd.cmd_discover(a)
    assert len(seen) == 1


# ---- ranking and the report ---------------------------------------------------

def row(name, **kw):
    base = {"name": name, "lane": "", "times": 3, "registry": "github", "hf_task": "",
            "card_tags": "[]", "attaches_to": "", "size_bytes": 0, "category": ""}
    base.update(kw)
    return base


def test_a_technique_repo_is_not_a_tool_wanted_nor_a_lane_wanted():
    rows = [row("a/engine"), row("b/paper-code", category="technique"),
            row("c/model", registry="huggingface", hf_task="translation")]
    assert [r["name"] for r in rank.tools_wanted(rows)] == ["a/engine"]
    assert [r["name"] for r in rank.wanted(rows)] == ["c/model"]


def test_a_technique_never_enters_the_model_queue():
    rows = [row("b/paper-code", lane="code", category="technique", registry="github"),
            row("c/model", lane="code", registry="huggingface", category="model")]
    got = rank.rank(rows, ceiling_gib=22.0)
    assert [r["name"] for r in got] == ["c/model"]


def tech(name, lane, title, times=1, last=NOW, url=None):
    return {"name": name, "lane": lane, "title": title, "times": times, "last_seen": last,
            "url": url or f"https://huggingface.co/papers/{name.split(':')[-1]}"}


def test_techniques_are_grouped_by_lane_most_seen_first():
    rows = [tech("arxiv:1", "code", "A", times=1), tech("arxiv:2", "code", "B", times=3),
            tech("arxiv:3", "image", "C"), tech("arxiv:4", "", "D")]
    groups = rank.techniques_wanted(rows)
    assert [g["lane"] for g in groups] == ["code", "image"]
    assert [t["name"] for t in groups[0]["techniques"]] == ["arxiv:2", "arxiv:1"]
    assert rank.techniques_laneless(rows) == 1


def test_techniques_wanted_can_be_scoped_to_a_lane():
    rows = [tech("arxiv:1", "code", "A"), tech("arxiv:3", "image", "C")]
    assert [g["lane"] for g in rank.techniques_wanted(rows, want="svg")] == ["code"]
    assert [g["lane"] for g in rank.techniques_wanted(rows, want="image")] == ["image"]


def test_the_report_prints_evidence_per_lane_and_decides_nothing():
    rows = [tech("arxiv:2", "code", "Speculative Decoding Done Right", times=3),
            tech("arxiv:3", "image", "Fewer Steps"), tech("arxiv:4", "", "Robot Policies")]
    text = "\n".join(loop._techniques_wanted_lines(rows))
    assert "=== techniques wanted ===" in text
    assert "Speculative Decoding Done Right" in text
    assert "https://huggingface.co/papers/2" in text
    line = next(l for l in text.splitlines() if "Speculative" in l)
    assert line.split()[0] == "3x"
    assert "1 technique(s) name no lane" in text
    for verdict in ("recommend", "should implement", "adopt", "better"):
        assert verdict not in text.lower()
    assert text.index("code") < text.index("image")


def test_no_techniques_prints_nothing():
    assert loop._techniques_wanted_lines([]) == []


@pytest.mark.gauntlet("state-is-whichever-row-came-last",
                     site="harness/memory_store/proposals.py:techniques")
def test_the_store_lists_techniques_with_their_evidence(conn):
    """A newer sighting from elsewhere does not replace the paper's own title and link."""
    papers.sweep(conn, get=Asked(), now=NOW)
    ms.record(conn, ms.Seen(name="arxiv:2610.07384", source="github-crowd",
                            url="https://github.com/a/wildmatch"))
    ms.record(conn, ms.Seen(name="org/model", source="s", category=ms.MODEL, lane="code"))
    got = {r["name"]: r for r in ms.techniques(conn)}
    assert "org/model" not in got
    t = got["arxiv:2610.07384"]
    assert t["lane"] == "image" and t["times"] == 2
    assert t["title"].startswith("WildMatch")
    assert t["url"] == "https://huggingface.co/papers/2610.07384"


def test_the_loop_prints_techniques_wanted(monkeypatch, tmp_path):
    from harness import papers as P
    store = ms.connect()
    try:
        P.sweep(store, get=Asked(), now=NOW)
    finally:
        store.close()
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    a = argparse.Namespace(run=False, lane="", top=1, json=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        loop._report_loop(a)
    text = out.getvalue()
    assert "=== techniques wanted ===" in text
    assert "WildMatch" in text


def test_a_model_the_feeds_link_is_recorded_as_a_model(conn, monkeypatch):
    from harness import discover
    monkeypatch.setattr(discover, "measured", lambda conn=None: set())
    src = feeds.Source("f", "https://feeds.invalid/a", kind="atom", lane="all")
    entry = feeds.Entry("new small model", "https://huggingface.co/org/tiny-coder",
                        body="Try https://huggingface.co/org/tiny-coder for code")
    discover.from_feeds(sources=[src], reader=lambda s: [entry], verify=False, store=conn)
    assert category(conn, "org/tiny-coder") == "model"
