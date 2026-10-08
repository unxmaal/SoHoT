"""A 429 is the upstream asking us to wait: retry, then record the source deferred, never failed. #630."""
from __future__ import annotations

import argparse
import json
import urllib.error
from pathlib import Path

import httpx
import pytest

from harness import benchmarks as bm
from harness import feeds
from harness import papers
from harness import memory_store as ms
from harness import ratelimit
from harness.commands import benchmarks as benchmarks_cmd
from harness.commands import discover as discover_cmd

FIX = Path(__file__).resolve().parent / "fixtures" / "papers" / "daily_papers.json"
NOW = 1_791_000_000.0
# The real readers, captured before conftest swaps them for network refusals.
REAL_GET = {papers: papers._get_json, bm: bm._get_json}


class Upstream:
    """httpx.get that answers each call with the next status in `codes`, repeating the last."""

    def __init__(self, *codes, body=None, headers=None):
        self.codes, self.calls = list(codes), []
        self.body = json.loads(FIX.read_text(encoding="utf-8")) if body is None else body
        self.headers = headers or {}

    def __call__(self, url, params=None, **kw):
        code = self.codes[min(len(self.calls), len(self.codes) - 1)]
        self.calls.append(url)
        req = httpx.Request("GET", url, params=params)
        if code == 200:
            return httpx.Response(200, json=self.body, request=req)
        return httpx.Response(code, headers=self.headers, request=req)


@pytest.fixture
def slept(monkeypatch):
    waits = []
    monkeypatch.setattr(ratelimit, "sleep", waits.append)
    return waits


def serve(monkeypatch, upstream):
    for module, real in REAL_GET.items():
        monkeypatch.setattr(module, "_get_json", real)
    monkeypatch.setattr(httpx, "get", upstream)
    return upstream


def test_a_429_then_a_200_is_read(monkeypatch, slept):
    up = serve(monkeypatch, Upstream(429, 200))
    conn = ms.connect()
    got = papers.sweep(conn, now=NOW)
    assert len(got) == 6 and len(up.calls) == 2 and len(slept) == 1
    assert ms.source_row(conn, papers.SOURCE)["last_status"] == "ok"


def test_retry_after_is_honoured_and_capped(monkeypatch, slept):
    serve(monkeypatch, Upstream(429, 429, 200, headers={"retry-after": "7"}))
    papers.sweep(ms.connect(), now=NOW)
    assert slept == [7.0, 7.0]
    slept.clear()
    serve(monkeypatch, Upstream(429, 200, headers={"retry-after": "86400"}))
    papers.sweep(ms.connect(), now=NOW, force=True)
    assert slept == [ratelimit.MAX_WAIT_S]


def test_a_source_that_is_always_429_is_deferred_not_failed(monkeypatch, slept):
    up = serve(monkeypatch, Upstream(429))
    conn = ms.connect()
    assert papers.sweep(conn, now=NOW) == []
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == ms.DEFERRED and "429" in row["last_error"]
    assert row["failures"] == 0 and row["last_read_at"] is None
    assert row["last_attempt_at"] == NOW
    assert len(up.calls) == ratelimit.ATTEMPTS


def test_a_500_still_fails(monkeypatch, slept):
    serve(monkeypatch, Upstream(500))
    conn = ms.connect()
    assert papers.sweep(conn, now=NOW) == []
    row = ms.source_row(conn, papers.SOURCE)
    assert row["last_status"] == "failed" and row["failures"] == 1


def test_a_404_fails_without_retrying(monkeypatch, slept):
    up = serve(monkeypatch, Upstream(404))
    papers.sweep(ms.connect(), now=NOW)
    assert len(up.calls) == 1 and slept == []


def test_a_deferral_keeps_the_failure_count_of_earlier_failed_reads():
    conn = ms.connect()
    ms.record_source(conn, "s", ok=False, error="HTTP 500", at=1.0)
    ms.record_source(conn, "s", deferred=True, error="HTTP 429", at=2.0)
    row = ms.source_row(conn, "s")
    assert (row["last_status"], row["failures"], row["last_attempt_at"]) == (ms.DEFERRED, 1, 2.0)


def papers_tier():
    return argparse.Namespace(papers=True, json=False, force=False, lane="")


def test_the_papers_tier_exits_0_when_its_source_is_rate_limited(monkeypatch, slept, capsys):
    serve(monkeypatch, Upstream(429))
    assert discover_cmd.cmd_discover(papers_tier()) == 0
    assert "rate-limited" in capsys.readouterr().out


def test_the_papers_tier_still_exits_1_on_a_500(monkeypatch, slept):
    serve(monkeypatch, Upstream(500))
    assert discover_cmd.cmd_discover(papers_tier()) == 1


def test_a_rate_limited_benchmark_registry_is_deferred_and_the_tier_exits_0(monkeypatch, slept,
                                                                            capsys):
    serve(monkeypatch, Upstream(429, body={}))
    monkeypatch.setattr(bm, "_read_gh", lambda lane, get: [])
    a = argparse.Namespace(lane="code", force=False, json=False)
    assert benchmarks_cmd.sweep_report(a) == 0
    assert "rate-limited benchmarks:huggingface:code" in capsys.readouterr().out
    row = ms.source_row(ms.connect(), "benchmarks:huggingface:code")
    assert row["last_status"] == ms.DEFERRED



def limited(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)


def broken(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)


@pytest.mark.parametrize("urlopen, status, failures", [(limited, ms.DEFERRED, 0),
                                                       (broken, "failed", 1)])
def test_an_atom_feed_that_stays_429_is_deferred_and_a_500_fails(monkeypatch, tmp_path,
                                                                 urlopen, status, failures):
    monkeypatch.setattr(feeds.urllib.request, "urlopen", urlopen)
    src = feeds.Source("limited-feed", "https://example.invalid/feed.atom")
    with pytest.raises(feeds.FeedError):
        feeds.read(src, cache_dir=tmp_path,
                   fetcher=lambda url: feeds.fetch(url, retries=1, sleep=lambda s: None))
    row = ms.source_row(ms.connect(), "limited-feed")
    assert (row["last_status"], row["failures"]) == (status, failures)
