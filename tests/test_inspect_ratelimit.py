"""inspect under an HF 429: Retry-After honoured, the batch paced, a persisting limit stops it with the rest queued. #797."""
import email.message
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402

from harness import github, inspect as ins, paths, ratelimit, reasons  # noqa: E402
from harness import memory_store as ms  # noqa: E402
from harness.commands import discover as discover_cmd  # noqa: E402

REPOS = ["hexgrad/Kokoro-82M", "dslim/bert-base-NER", "BAAI/bge-reranker-base"]
ARGS = type("A", (), {"repos": [], "from_store": True, "top": 10, "budget": 10,
                      "shard": "", "judge": False, "json": False})


class Registry:
    """urlopen for the HF model API: 429 while `limited` says so, else the recorded card."""

    def __init__(self, limited, retry_after="7"):
        self.limited, self.retry_after = limited, retry_after
        self.asked: list[tuple[str, dict]] = []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.asked.append((url, dict(req.header_items())))
        if self.limited(len(self.asked)):
            hdrs = email.message.Message()
            if self.retry_after is not None:
                hdrs["Retry-After"] = self.retry_after
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs, None)
        model_id = url.split("/api/models/", 1)[-1].split("?", 1)[0]
        return io.BytesIO(json.dumps(fakes.card(model_id)).encode())


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "lh"))
    monkeypatch.setattr(paths, "home", lambda: tmp_path / "lh")
    monkeypatch.setattr(ratelimit, "hf_headers", lambda url: {}, raising=False)
    slept: list[float] = []
    monkeypatch.setattr(ratelimit, "sleep", slept.append)
    monkeypatch.setattr(ratelimit.time, "time", lambda: 1000.0)

    class Client:
        stale: list = []
        spent = 0

        def __init__(self, **kw):
            pass

        def repo(self, name):
            raise AssertionError(f"GitHub asked about {name}")
    monkeypatch.setattr(github, "Client", Client)
    db = ms.connect()
    for repo in REPOS:
        ms.record(db, ms.Seen(name=repo, source="t", registry=ms.HUGGINGFACE, resolved=repo))
        ms.decide(db, repo, "queued", tier=ms.INSPECT, detail="swept", reason=reasons.CANDIDATE)
    db.close()
    return slept


def _run(monkeypatch, registry, capsys):
    monkeypatch.setattr(urllib.request, "urlopen", registry)
    rc = discover_cmd._report_inspect(ARGS())
    return rc, capsys.readouterr()


def _verdicts():
    db = ms.connect()
    try:
        return {r["name"]: (r["state"], r["n"]) for r in db.execute(
            "SELECT p.name, p.state, COUNT(v.id) AS n FROM proposals p "
            "LEFT JOIN verdicts v ON v.proposal_id = p.id GROUP BY p.id")}
    finally:
        db.close()


def test_retry_after_is_honoured_on_the_retry(world, monkeypatch, capsys):
    reg = Registry(limited=lambda n: n == 1, retry_after="7")
    rc, _ = _run(monkeypatch, reg, capsys)
    assert rc == 0
    assert world[0] == 7.0, world


def test_one_429_slows_every_later_call_in_the_batch(world, monkeypatch, capsys):
    reg = Registry(limited=lambda n: n == 1, retry_after="0")
    rc, _ = _run(monkeypatch, reg, capsys)
    assert rc == 0
    asked = {u.split("/api/models/")[1].split("?")[0] for u, _ in reg.asked}
    assert asked == set(REPOS)
    # the retry itself, then a paced wait before each of the two later candidates
    paced = [s for s in world[1:] if s > 0]
    assert len(paced) >= len(REPOS) - 1, world


def test_a_persisting_429_stops_the_batch_and_leaves_the_rest_queued(world, monkeypatch, capsys):
    before = _verdicts()
    reg = Registry(limited=lambda n: True)
    rc, got = _run(monkeypatch, reg, capsys)
    assert rc == 0
    asked = {u.split("/api/models/")[1].split("?")[0] for u, _ in reg.asked}
    assert len(asked) == 1, reg.asked
    assert len(reg.asked) == ins.SIZE_RETRIES + 1
    assert _verdicts() == before
    assert "left queued for the next sweep" in got.out


def test_an_unrouted_name_under_a_429_is_not_sent_to_github(world, monkeypatch, capsys):
    db = ms.connect()
    db.execute("UPDATE proposals SET registry = ''")
    db.commit()
    db.close()
    rc, _ = _run(monkeypatch, Registry(limited=lambda n: True), capsys)
    assert rc == 0


def test_inspect_requests_carry_the_hf_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    reg = Registry(limited=lambda n: False)
    monkeypatch.setattr(urllib.request, "urlopen", reg)
    ins.hf_model(REPOS[0])
    assert dict(reg.asked[0][1]).get("Authorization") == "Bearer hf_test"


def test_the_token_goes_only_to_huggingface(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    assert ratelimit.hf_headers("https://huggingface.co/api/models/a/b") == {"Authorization": "Bearer hf_test"}
    assert ratelimit.hf_headers("https://www.reddit.com/r/x/.rss") == {}
    assert ratelimit.hf_headers("https://huggingface.co.evil.test/x") == {}


def test_get_json_carries_the_hf_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    seen = {}

    def get(url, **kw):
        seen.update(kw.get("headers") or {})
        return httpx.Response(200, json={}, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)
    ratelimit.get_json("https://huggingface.co/api/models/a/b")
    assert seen.get("Authorization") == "Bearer hf_test"
