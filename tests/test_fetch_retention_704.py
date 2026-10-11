"""Budgets, retries and grace periods that decided a candidate's fate by a fact about the harness. #704."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
import urllib.error

import pytest

from harness import disk, downloads, feeds, fetching, knobs, papers, ratelimit
from harness import inspect as ins
from harness import memory_store as ms
from tests.test_harness_disk import NOW, DAY, _blob, inv, make_repo, verdict, world  # noqa: F401
from tests.test_harness_fetching_budget import _seed, _sizes, store  # noqa: F401
from tests.test_harness_inspect import tree
from tests.test_harness_registry import _no_model

GIB = fetching.GIB
REPO = Path(__file__).resolve().parents[1]


def _latest_fetch(conn, name):
    return conn.execute(
        "SELECT v.outcome, v.until FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
        "WHERE p.name = ? AND v.tier = 'fetch' ORDER BY v.id DESC LIMIT 1", (name,)).fetchone()


def test_a_candidate_bigger_than_the_whole_budget_says_what_would_end_the_wait(store):
    _seed(store, "org/huge", 45)
    fetching.run(store, _sizes(store), limit=5, free=500 * GIB, budget=int(40 * GIB))
    row = _latest_fetch(store, "org/huge")
    assert row["outcome"] == "queued"
    assert row["until"] == "limit:download_budget_gib>40"


def test_a_candidate_over_only_what_is_left_of_the_budget_waits_for_the_next_sweep(store):
    _seed(store, "org/a-first", 30)
    _seed(store, "org/b-second", 20)
    fetching.run(store, _sizes(store), limit=5, free=500 * GIB, budget=int(40 * GIB))
    row = _latest_fetch(store, "org/b-second")
    assert row["outcome"] == "queued" and not row["until"]


def test_the_download_budget_is_a_registered_knob_with_a_limit():
    k = knobs.KNOBS["download_budget"]
    assert k.limit == "download_budget_gib"
    assert "scripts/serve-discover.sh:DISCOVER_BUDGET_GIB" in k.sites
    assert knobs.limits()["download_budget_gib"] == 40


def test_a_429_on_the_small_variants_only_is_unknown_not_too_big(tmp_path):
    names = {"org/m-1b": None, "org/m-2b": None, "org/m-70b": 140 * GIB, "org/m-90b": 180 * GIB}
    code = "\n".join(f'load("{n}")' for n in names) + "\nif __name__ == '__main__':\n    main()\n"
    tree(tmp_path / "org__app", {"app.py": code, ".git/HEAD": ""})

    def facts(model_id, cache=None):
        size = names[model_id]
        if size is None:
            return {"size": -1, "lane": "", "deferred": True}
        return {"size": size, "lane": "code"}

    got = ins.inspect("org/app", tmp_path, facts=facts, run=lambda *a, **k: "2026-01-01T00:00:00+00:00",
                      ceiling=66 * GIB)
    assert sorted(got.unsized) == ["org/m-1b", "org/m-2b"]
    assert got.verdict == "unknown"
    assert "rate" in got.why


def test_a_rate_limited_size_is_reported_deferred_by_hf_facts():
    def fetch(url):
        raise feeds.RateLimitedFeed(f"{url}: gave up (HTTP 429)")
    assert ins.hf_facts("org/x", fetch=fetch) == {"size": -1, "lane": "", "deferred": True}


def test_a_missing_model_is_unsized_but_not_deferred():
    def fetch(url):
        raise feeds.FeedError(f"{url}: HTTP 404")
    assert not ins.hf_facts("org/x", fetch=fetch).get("deferred")


class _Seq:
    def __init__(self, url, errors):
        self.url, self.errors, self.calls = url, list(errors), 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)

        class R:
            def read(self):
                return b"<feed/>"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()


def test_feeds_waits_as_retry_after_directs_up_to_the_cap(monkeypatch):
    url = "https://example.invalid/f.rss"
    seq = _Seq(url, [urllib.error.HTTPError(url, 429, "Too Many", {"Retry-After": "300"}, None)])
    monkeypatch.setattr(feeds.urllib.request, "urlopen", seq)
    waits = []
    assert feeds.fetch(url, sleep=waits.append) == "<feed/>"
    assert waits == [ratelimit.MAX_WAIT_S]
    seq = _Seq(url, [urllib.error.HTTPError(url, 429, "Too Many", {"Retry-After": "45"}, None)])
    monkeypatch.setattr(feeds.urllib.request, "urlopen", seq)
    waits.clear()
    feeds.fetch(url, sleep=waits.append)
    assert waits == [45.0]


def test_feeds_backs_off_rather_than_waiting_a_fixed_delay(monkeypatch):
    url = "https://example.invalid/f.rss"
    seq = _Seq(url, [urllib.error.HTTPError(url, 429, "Too Many", {}, None)] * 3)
    monkeypatch.setattr(feeds.urllib.request, "urlopen", seq)
    waits = []
    feeds.fetch(url, delay=5.0, sleep=waits.append)
    assert waits == [5.0, 10.0, 20.0]


def test_a_dead_host_is_not_retried_like_a_rate_limit(monkeypatch):
    url = "https://example.invalid/f.rss"
    seq = _Seq(url, [urllib.error.URLError("timed out")] * 10)
    monkeypatch.setattr(feeds.urllib.request, "urlopen", seq)
    with pytest.raises(feeds.FeedError):
        feeds.fetch(url, sleep=lambda s: None)
    assert seq.calls == 2


def test_a_repo_whose_fourth_weight_is_the_only_one_that_fits_queues_it():
    fit = ins.Fit(repo="org/app", headline=["org/a-bf16", "org/b-bf16", "org/c-bf16", "org/d-4bit"],
                  weights={"org/a-bf16": 140 * GIB, "org/b-bf16": 130 * GIB,
                           "org/c-bf16": 120 * GIB, "org/d-4bit": 20 * GIB})
    assert ins.fetchable_weights(fit, 66 * GIB) == ["org/d-4bit"]


def test_fetchable_weights_keeps_headline_order_and_three_at_most():
    fit = ins.Fit(repo="org/app", headline=["a/1", "a/2", "a/3", "a/4", "a/5"],
                  weights={f"a/{i}": GIB for i in range(1, 6)})
    assert ins.fetchable_weights(fit, 66 * GIB) == ["a/1", "a/2", "a/3"]


def test_a_dead_fetch_partial_download_is_cleared(world):
    d = make_repo(world.hub, "org/dead", recorded=False)
    part = _blob(d, "part.incomplete")
    # A fetch in another process that started and then died without finishing.
    child = ("import sys\nfrom harness import downloads, memory_store as ms\n"
             "downloads.start(ms.connect(), 'org/dead', downloads.HUB, sys.argv[1])\n")
    subprocess.run([sys.executable, "-c", child, str(d)], cwd=REPO, check=True)
    disk.clean(inv(world), time.time(), world.conn)
    assert not part.exists()


def test_a_live_fetch_older_than_a_day_keeps_its_partial_blobs(world):
    d = make_repo(world.hub, "org/slow", recorded=False)
    part = _blob(d, "part.incomplete")
    rid = downloads.start(world.conn, "org/slow", downloads.HUB, d)
    try:
        row = dict(world.conn.execute("SELECT * FROM downloads WHERE id = ?", (rid,)).fetchone())
        assert downloads.in_flight(row, time.time() + 3 * DAY)
        disk.clean(inv(world), time.time() + 3 * DAY, world.conn)
        assert part.exists()
    finally:
        downloads.release(rid)


def test_a_retest_seven_days_on_still_finds_the_weights(world):
    d = make_repo(world.hub, "org/retest")
    verdict(world.conn, "org/retest", "broken", at=NOW - 2 * DAY)
    world.conn.execute("UPDATE proposals SET next_retest_at = ? WHERE name = 'org/retest'",
                       (NOW + 5 * DAY,))
    world.conn.commit()
    i = inv(world)
    assert disk.delete(i, NOW, disk.REJECTED, world.conn) == []
    assert d.exists()


def test_weights_with_no_retest_pending_still_go_after_the_grace(world):
    d = make_repo(world.hub, "org/done")
    verdict(world.conn, "org/done", "broken", at=NOW - 2 * DAY)
    world.conn.execute("UPDATE proposals SET next_retest_at = NULL WHERE name = 'org/done'")
    world.conn.commit()
    disk.delete(inv(world), NOW, disk.REJECTED, world.conn)
    assert not d.exists()


def test_a_ten_day_outage_continues_the_backlog(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    now = 1_791_000_000.0
    ms.record_source(conn, papers.SOURCE, kind=papers.KIND, url=papers.API, at=now - 10 * DAY)
    asked = []
    papers.sweep(conn, get=lambda url, params=None: asked.append(params["date"]) or [], now=now)
    first = sorted(asked)
    assert first[0] == papers._day(now - 9 * DAY) and len(first) == papers.MAX_DAYS
    asked.clear()
    papers.sweep(conn, get=lambda url, params=None: asked.append(params["date"]) or [], now=now)
    assert sorted(asked) == [papers._day(now - d * DAY) for d in (2, 1, 0)]


def test_inspect_queues_a_fourth_headline_weight_that_fits_rather_than_retiring_it(tmp_path, monkeypatch):
    from harness import cli, github, paths
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/app", source="t", registry=ms.GITHUB, resolved="org/app"))
    ms.record(conn, ms.Seen(name="org/d-4bit", source="inspect", kind="weights",
                            registry=ms.HUGGINGFACE, resolved="org/d-4bit", lane="code"))
    ms.link(conn, "org/app", "org/d-4bit", "needs")
    ms.decide(conn, "org/d-4bit", "queued", tier=ms.INSPECT, detail="named by org/app")
    conn.close()

    class Client:
        stale: list = []
        spent = 0

        def __init__(self, **kw):
            pass

        def repo(self, name):
            return {"size": 10, "description": "an app"}

    weights = {"org/a-bf16": 140 * GIB, "org/b-bf16": 130 * GIB,
               "org/c-bf16": 120 * GIB, "org/d-4bit": 20 * GIB}
    monkeypatch.setattr(github, "Client", Client)
    monkeypatch.setattr(ins, "ceiling_bytes", lambda *a, **k: 66 * GIB)
    monkeypatch.setattr(ins, "inspect", lambda repo, work, meta=None, **kw: ins.Fit(
        repo=repo, registry=ms.GITHUB, verdict="fits", weights=dict(weights),
        headline=list(weights), lanes={m: "code" for m in weights}))
    monkeypatch.setattr(ins, "hf_model", _no_model)
    args = type("A", (), {"repos": ["org/app"], "from_store": False, "top": 10, "budget": 10,
                          "shard": "", "judge": False, "json": False})()
    assert cli._report_inspect(args) == 0
    conn = ms.connect()
    try:
        assert ms.latest(conn, "org/d-4bit")["outcome"] == "queued"
        assert all(ms.latest(conn, m) is None or ms.latest(conn, m)["outcome"] != "queued"
                   for m in ("org/a-bf16", "org/b-bf16", "org/c-bf16"))
    finally:
        conn.close()


def test_the_budget_registry_reads_the_environment_the_sweep_runs_with(monkeypatch):
    monkeypatch.setenv("DISCOVER_BUDGET_GIB", "30")
    assert knobs.limits()["download_budget_gib"] == 30
    assert knobs.KNOBS["download_budget"].default() == 30


def test_a_manual_run_with_no_budget_uses_the_registered_budget(tmp_path, monkeypatch):
    from harness import cli
    from harness.commands import screen as screen_cmd
    monkeypatch.delenv("DISCOVER_BUDGET_GIB", raising=False)
    a = cli.build_parser().parse_args(["discover"])
    assert a.budget_gib is None or a.budget_gib == 40
    seen = {}

    def run(conn, *args, budget=None, **kw):
        seen["budget"] = budget
        return []
    monkeypatch.setattr(fetching, "run", run)
    monkeypatch.setattr(fetching, "queued", lambda *a, **k: [{"name": "org/x", "lane": "code"}])
    screen_cmd.cmd_fetch(type("A", (), {"run": True, "limit": 1, "lane": "", "budget_gib": a.budget_gib,
                                        "json": False})())
    assert seen["budget"] == 40 * GIB


def test_a_candidate_waiting_on_a_bigger_budget_is_not_retried_at_the_same_budget(store):
    _seed(store, "org/huge", 45)
    sizes = _sizes(store)
    fetching.run(store, sizes, limit=5, free=500 * GIB, budget=int(40 * GIB))
    before = store.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    got = fetching.run(store, sizes, limit=5, free=500 * GIB, budget=int(40 * GIB))
    assert got == []
    assert store.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == before
    got = fetching.run(store, sizes, limit=5, free=500 * GIB, budget=int(80 * GIB))
    assert [g["repo"] for g in got if g["ok"]] == ["org/huge"]


def test_retry_after_as_an_http_date_is_honoured():
    from email.utils import formatdate
    when = formatdate(time.time() + 60, usegmt=True)
    assert 55 <= ratelimit.wait_s(when, 0) <= 61
    assert ratelimit.wait_s(formatdate(time.time() - 60, usegmt=True), 3) == 0.0
    assert ratelimit.wait_s("not a date", 2) == 4.0
