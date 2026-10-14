"""The 01:00Z sweep asks for a day HF has published, and a 400 for an unpublished day is deferred, not failed. #859."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
import pytest

from harness import papers
from harness import memory_store as ms
from harness import ratelimit
from harness.commands import discover as discover_cmd

FIX = Path(__file__).resolve().parent / "fixtures" / "papers" / "daily_papers.json"
DAY = 86400.0
MIDNIGHT = 1_790_985_600.0          # 2026-10-03 00:00Z
NOW = MIDNIGHT + 3600.0             # the nightly sweep: 21:00 EDT = 01:00Z
TODAY = time.strftime("%Y-%m-%d", time.gmtime(NOW))
YESTERDAY = time.strftime("%Y-%m-%d", time.gmtime(NOW - DAY))
REAL_GET = papers._get_json


class Published:
    """httpx.get for daily_papers: 200 for a published date, 400 for one that is not (or every date)."""

    def __init__(self, unpublished=(TODAY,), undated=200):
        self.unpublished, self.undated, self.dates = set(unpublished), undated, []

    def __call__(self, url, params=None, **kw):
        date = (params or {}).get("date")
        self.dates.append(date)
        req = httpx.Request("GET", url, params=params)
        code = self.undated if date is None else (
            400 if "*" in self.unpublished or date in self.unpublished else 200)
        if code == 200:
            return httpx.Response(200, json=json.loads(FIX.read_text(encoding="utf-8")), request=req)
        return httpx.Response(code, request=req)


@pytest.fixture
def hf(monkeypatch):
    monkeypatch.setattr(ratelimit, "sleep", lambda s: None)
    monkeypatch.setattr(papers, "_get_json", REAL_GET)

    def serve(upstream):
        monkeypatch.setattr(httpx, "get", upstream)
        return upstream
    return serve


def read_last_night(conn, now=NOW - DAY):
    """The source as a sweep 24 h earlier left it: read through the day before that sweep."""
    papers.sweep(conn, get=lambda url, params=None: [], now=now)
    return ms.source_row(conn, papers.SOURCE)["last_read_at"]


def test_the_01z_sweep_reads_yesterday_and_never_asks_for_today(hf):
    up = hf(Published())
    conn = ms.connect()
    read_last_night(conn)
    got = papers.sweep(conn, now=NOW)
    assert got and TODAY not in up.dates and up.dates == [YESTERDAY]
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == "ok" and row["failures"] == 0


def test_a_first_read_uses_the_undated_page_and_the_next_night_asks_for_the_day_after(hf):
    up = hf(Published())
    conn = ms.connect()
    papers.sweep(conn, now=NOW)
    assert up.dates == [None]
    papers.sweep(conn, now=NOW + DAY)
    assert up.dates == [None, TODAY]


def test_a_400_that_persists_is_deferred_not_failed(hf):
    up = hf(Published(unpublished=("*",)))
    conn = ms.connect()
    before = read_last_night(conn)
    assert papers.sweep(conn, now=NOW) == []
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == ms.DEFERRED and "400" in row["last_error"]
    assert row["failures"] == 0 and row["last_read_at"] == before
    assert up.dates == [YESTERDAY]
    papers.sweep(conn, now=NOW + 3600)
    assert up.dates == [YESTERDAY, YESTERDAY]


def test_the_days_read_before_an_unpublished_one_are_kept(hf):
    up = hf(Published(unpublished=(YESTERDAY,)))
    conn = ms.connect()
    read_last_night(conn, now=NOW - 3 * DAY)
    papers.sweep(conn, now=NOW)
    first = up.dates[:]
    assert first[-1] == YESTERDAY and len(first) == 3
    assert ms.source_row(conn, papers.SOURCE)["last_status"] == ms.DEFERRED
    up.unpublished = set()
    papers.sweep(conn, now=NOW + 3600)
    assert up.dates[len(first):] == [YESTERDAY]


def test_a_400_on_the_undated_page_still_fails(hf):
    hf(Published(undated=400))
    conn = ms.connect()
    papers.sweep(conn, now=NOW)
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == "failed" and row["failures"] == 1


def test_the_papers_tier_exits_0_when_the_day_is_not_published_yet(hf, monkeypatch, capsys):
    hf(Published(unpublished=("*",)))
    conn = ms.connect()
    read_last_night(conn, now=time.time() - 3 * DAY)
    conn.close()
    a = argparse.Namespace(papers=True, json=False, force=False, lane="")
    assert discover_cmd.cmd_discover(a) == 0
    assert "not published yet" in capsys.readouterr().out
