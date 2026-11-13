"""Gauntlet WR (#1784): each stored value a production writer sets is read back by a production reader."""
import json

import pytest

from harness import cli, discover, feeds, human, usage
from harness import memory_store as ms
from harness.memory_store.migrations import legacy


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _votes(conn, lane, answers):
    for answer, first, voter in answers:
        human.record(lane, "frog", "alpha", "beta", answer, shown_first=first, run="", voter=voter, conn=conn)


def test_the_side_shown_first_and_the_voter_are_read_back_as_side_bias(conn, capsys):
    _votes(conn, "svg", [("a", "alpha", "voter-one"), ("a", "alpha", "voter-one"), ("b", "beta", "voter-one"),
                         ("b", "alpha", "voter-two"), ("tie", "alpha", "voter-two"), ("a", "", "voter-two")])
    conn.commit()
    side = human.metric_agreement(conn)["side"]
    assert side["svg"]["decided"] == 4 and side["svg"]["first_won"] == 3
    assert side["svg"]["voters"] == {"voter-one": {"decided": 3, "first_won": 3}, "voter-two": {"decided": 1, "first_won": 0}}
    assert side["svg"]["p"] == pytest.approx(0.625)
    assert cli.main(["votes", "--store", str(ms.db_path())]) == 0
    out = capsys.readouterr().out
    assert "svg: the side shown first won 3 of 4 vote(s)" in out
    assert "voter-one 3 of 3, voter-two 0 of 1" in out


def test_the_side_count_follows_the_lane_asked_for(conn):
    _votes(conn, "svg", [("a", "alpha", "voter-one")])
    _votes(conn, "web", [("b", "alpha", "voter-one")])
    conn.commit()
    assert set(human.metric_agreement(conn, "web")["side"]) == {"web"}
    assert human.metric_agreement(conn, "web")["side"]["web"]["first_won"] == 0


def _request(conn, prompt, lane="code"):
    row = {c: "" for c in usage.COLUMNS} | {"stream": 0, "tool_calls": 0, "tool_calls_valid": 0}
    usage.insert(conn, [(row | {"at": 1000.0, "alias": f"sohot-{lane}", "lane": lane, "purpose": "work",
                                "prompt_tokens": None, "completion_tokens": None, "ttft_s": None, "total_s": None},
                         {"prompt": prompt, "completion": f"answer to {prompt}"})])


def test_kept_text_samples_are_read_back_with_their_request(conn, capsys):
    usage.set_text(conn, True)
    _request(conn, "first prompt")
    _request(conn, "second prompt", lane="extract")
    got = usage.samples(conn, 5)
    assert [s["prompt"] for s in got] == ["second prompt", "first prompt"]
    assert got[0]["alias"] == "sohot-extract" and got[0]["completion"] == "answer to second prompt"
    assert [s["prompt"] for s in usage.samples(conn, 5, lane="code")] == ["first prompt"]
    assert cli.main(["usage", "--samples", "1"]) == 0
    out = capsys.readouterr().out
    assert "prompt: second prompt" in out and "first prompt" not in out


def test_turning_text_off_deletes_the_kept_samples(conn, capsys):
    usage.set_text(conn, True)
    _request(conn, "kept prompt")
    assert cli.main(["usage", "--text", "off", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] == 1
    assert usage.samples(conn, 5) == []
    assert conn.execute("SELECT count(*) FROM gateway_samples").fetchone()[0] == 0


def test_a_retired_source_is_listed_with_its_reason_until_a_read_of_it_succeeds(conn, capsys, monkeypatch):
    ms.record_source(conn, "ghost")
    assert legacy.retire_unread_sources(conn) == 1
    conn.commit()
    ms.record_source(conn, "ghost", ok=False, error="boom")
    ms.record_source(conn, "ghost", deferred=True, error="429")
    assert [r["name"] for r in feeds.retired(conn)] == ["ghost"]
    assert feeds.retired(conn)[0]["why"] == feeds.retired_reason("ghost")
    monkeypatch.setattr(feeds, "staleness", lambda: [])
    monkeypatch.setattr(discover, "feed_sources", lambda: [])
    assert cli.main(["discover", "--sources", "--json"]) == 0
    assert [r["name"] for r in json.loads(capsys.readouterr().out)["retired"]] == ["ghost"]
    ms.record_source(conn, "ghost", kind="rss", url="https://example.invalid/feed")
    assert feeds.retired(conn) == []
