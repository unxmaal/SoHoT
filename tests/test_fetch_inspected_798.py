"""Fetch takes only an answered inspect, and refuses a listing with no weights a runner loads. #798."""
from __future__ import annotations

import pytest

from harness import fetching, reasons
from harness import memory_store as ms
from tests.test_runner_base_weights import Snapshot, db  # noqa: F401

GIB = fetching.GIB
FREE = 900 * GIB


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())


def _queue(db, name, size=GIB // 2):
    ms.record(db, ms.Seen(name=name, source="t", resolved=name, kind="weights", lane="code",
                          registry=ms.HUGGINGFACE))
    ms.set_size(db, name, size)
    ms.decide(db, name, "queued", tier="inspect", detail="fits", size_bytes=size,
              reason=reasons.CANDIDATE)


def _listing(files):
    return lambda repo: [{"rfilename": f, "size": 100} for f in files]


def _latest(db, name):
    return db.execute("SELECT v.outcome, v.tier, v.reason, v.detail FROM verdicts v "
                      "JOIN proposals p ON p.id = v.proposal_id WHERE p.name = ? "
                      "ORDER BY v.id DESC LIMIT 1", (name,)).fetchone()


def _reopen_for_retest(db, name):
    ms.decide(db, name, "broken", tier="screen", detail="it ran and passed nothing")
    ms.decide(db, name, "queued", tier="inspect", detail="retest 1/3: broken at screen",
              reopen=ms.RETEST, reopen_why="retest 1/3")


def test_a_reopened_candidate_whose_inspect_has_not_answered_is_not_fetched(db):
    name = "QLNI/SHADOW-250M"
    _queue(db, name)
    _reopen_for_retest(db, name)
    snap = Snapshot()
    done = fetching.run(db, limit=5, free=FREE, snapshot=snap,
                        listing=_listing(["config.json", "model.safetensors"]))
    assert snap.asked == []
    assert not done[0]["ok"] and "inspect" in done[0]["why"]
    assert _latest(db, name)["reason"] == reasons.REOPENED


def test_the_reopened_candidate_is_fetched_once_inspect_answers_again(db):
    name = "org/Retested-1B"
    _queue(db, name)
    _reopen_for_retest(db, name)
    ms.decide(db, name, "queued", tier="inspect", detail="fits", size_bytes=GIB // 2,
              reason=reasons.CANDIDATE)
    snap = Snapshot()
    fetching.run(db, limit=5, free=FREE, snapshot=snap,
                 listing=_listing(["config.json", "model.safetensors"]))
    assert snap.asked == [name]


def test_an_inspect_deferred_by_the_harness_is_not_an_answer(db):
    name = "org/Deferred-1B"
    _queue(db, name)
    _reopen_for_retest(db, name)
    ms.decide(db, name, "queued", tier="inspect", detail="rate-limited", reason=reasons.HARNESS)
    snap = Snapshot()
    fetching.run(db, limit=5, free=FREE, snapshot=snap,
                 listing=_listing(["config.json", "model.safetensors"]))
    assert snap.asked == []


def test_weights_only_in_a_format_no_runner_loads_are_refused_before_fetch(db):
    name = "QLNI/SHADOW-250M"
    _queue(db, name)
    snap = Snapshot()
    done = fetching.run(db, limit=5, free=FREE, snapshot=snap, listing=_listing(
        ["config.json", "finetune/shadow250m_instruct.pt", "deployment/shadow250m_instruct.shdw",
         "README.md"]))
    assert snap.asked == []
    row = _latest(db, name)
    assert (row["outcome"], row["tier"], row["reason"]) == ("declined", "fetch", reasons.CANDIDATE)
    assert "runners wanted" in row["detail"] and ".pt" in row["detail"]
    assert not done[0]["ok"]


def test_a_repo_with_no_weights_at_all_is_refused_before_fetch(db):
    name = "peculiar-ragdoll/Qwen-Sharp-Chat-Templates"
    _queue(db, name, size=3854335)
    snap = Snapshot()
    fetching.run(db, limit=5, free=FREE, snapshot=snap, listing=_listing(
        ["README.md", "chat_template.jinja", "chat_template_oneline.txt", "scripts/apply.py"]))
    assert snap.asked == []
    row = _latest(db, name)
    assert row["outcome"] == "declined" and row["detail"].startswith("no weights")
    assert fetching.queued(db) == []


def test_only_the_repo_with_loadable_weights_is_downloaded(db):
    _queue(db, "org/a-templates")
    _queue(db, "org/b-model")
    files = {"org/a-templates": ["README.md"], "org/b-model": ["config.json", "model.safetensors"]}
    snap = Snapshot()
    fetching.run(db, limit=2, free=FREE, snapshot=snap,
                 listing=lambda repo: [{"rfilename": f, "size": 1} for f in files[repo]])
    assert snap.asked == ["org/b-model"]


@pytest.mark.parametrize("files", [["model.safetensors"], ["m-Q4_K_M.gguf"],
                                   ["pytorch_model.bin", "config.json"], ["weights.npz"],
                                   ["unet/diffusion_pytorch_model.safetensors"]])
def test_a_listing_with_a_loadable_format_has_no_gap(files):
    assert fetching.weights_gap([{"rfilename": f} for f in files]) == ""


def test_a_dependency_is_not_held_to_the_weights_rule(db):
    snap = Snapshot()
    fetching.download("org/tokenizer-only", snapshot=snap, listing=_listing(["tokenizer.json"]),
                      text=False, conn=db)
    assert snap.asked == ["org/tokenizer-only"]


@pytest.mark.gauntlet("a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject",
                      site="harness/fetching.py:run")
def test_a_failed_listing_is_not_recorded_as_a_refusal_of_the_candidate(db):
    name = "org/Unlisted-1B"
    _queue(db, name)

    def broken(repo):
        raise OSError("connection reset")
    done = fetching.run(db, limit=5, free=FREE, snapshot=Snapshot(), listing=broken)
    assert not done[0]["ok"] and "listing failed" in done[0]["why"]
    row = _latest(db, name)
    assert (row["outcome"], row["tier"]) == ("queued", "inspect")
