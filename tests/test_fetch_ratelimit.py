"""A registry 429 on the fetch tier's listing: the id printed once, the rest of the tier deferred. #675."""
import types

import httpx
import pytest

from harness import feeds, fetching, ratelimit
from harness import memory_store as ms
from harness.commands import screen as screen_cmd

GIB = 1024 ** 3
REPOS = ["org/First-4B-GGUF", "org/Second-4B-GGUF", "org/Third-4B-GGUF"]


@pytest.fixture
def queue(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "lh"))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(tmp_path / "gguf"))
    (tmp_path / "gguf").mkdir()
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    monkeypatch.setattr(fetching, "free_bytes", lambda path=None: 900 * GIB)
    monkeypatch.setattr(ratelimit, "sleep", lambda s: None)
    db = ms.connect()
    for i, repo in enumerate(REPOS):
        ms.record(db, ms.Seen(name=repo, source="t", resolved=repo, kind="weights", lane="code"))
        ms.set_size(db, repo, int(2.5 * GIB))
        ms.decide(db, repo, "queued", tier="inspect", size_bytes=int(2.5 * GIB))
    db.close()
    calls = []

    def get(url, **kw):
        calls.append(url)
        return httpx.Response(429, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)

    def old_fetch(url, **kw):
        calls.append(url)
        raise feeds.RateLimitedFeed(f"{url}: gave up after 2 attempts (HTTP 429)")
    monkeypatch.setattr(feeds, "fetch", old_fetch)
    return calls


def _fetch(capsys):
    rc = screen_cmd.cmd_fetch(types.SimpleNamespace(run=True, limit=5, lane="", budget_gib=None))
    return rc, capsys.readouterr().out


def test_a_429_listing_prints_the_repo_id_once(queue, capsys):
    rc, out = _fetch(capsys)
    line = next(ln for ln in out.splitlines() if "skip" in ln)
    first = next(r for r in REPOS if r in line)
    assert line.count(first) == 1, line
    assert "429" in line


def test_a_rate_limited_listing_defers_the_rest_of_the_tier_and_exits_0(queue, capsys):
    rc, out = _fetch(capsys)
    assert rc == 0
    assert len(queue) == ratelimit.ATTEMPTS
    first = next(r for r in REPOS if r in queue[0])
    assert all(first in url for url in queue)
    assert [r for r in REPOS if r in out] == [first]
    db = ms.connect()
    try:
        states = {r["name"]: r["state"] for r in db.execute("SELECT name, state FROM proposals")}
    finally:
        db.close()
    assert states == {r: "queued" for r in REPOS}


def test_a_rate_limited_listing_is_marked_deferred_in_the_tier_result(queue):
    db = ms.connect()
    try:
        done = fetching.run(db, limit=5)
    finally:
        db.close()
    assert len(done) == 1 and done[0]["repo"] in REPOS
    assert done[0]["deferred"] and not done[0]["ok"]


def test_a_listing_failure_other_than_429_names_the_repo_once_and_moves_on(queue, monkeypatch):
    def get(url, **kw):
        queue.append(url)
        return httpx.Response(404, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)
    db = ms.connect()
    try:
        done = fetching.run(db, limit=5)
    finally:
        db.close()
    assert sorted(d["repo"] for d in done) == REPOS
    assert all(d["repo"] not in d["why"] for d in done), done
    assert all("HTTP 404" in d["why"] for d in done), done


@pytest.mark.parametrize("bases", [[], ["org/base-a", "org/base-b"]])
def test_a_rate_limited_dependency_stops_the_remaining_ones(bases):
    tried = []

    def fetch(dep):
        tried.append(dep)
        raise fetching.FetchDeferred("listing rate-limited")
    done, spent, _ = fetching._fetch_needs(
        "org/M", ["org/base-a", "org/base-b"], bases=bases, sizes={"org/base-a": 1, "org/base-b": 1},
        sizer=lambda r: 1, budget=None, spent=0, free=900 * GIB, floor=0, fetch=fetch)
    assert tried == ["org/base-a"]
    assert [d.get("deferred") for d in done] == [True]
