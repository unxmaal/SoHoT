"""A runner's declared base weights are fetched like a dependency, or the candidate waits for them. #632."""
from __future__ import annotations

import pytest

from harness import downloads, fetching, reasons, screen
from harness import memory_store as ms

GIB = fetching.GIB
OMNI = "OmniSVG/OmniSVG1.1_4B"
BASE = "Qwen/Qwen2.5-VL-3B-Instruct"
FREE = 900 * GIB


@pytest.fixture
def db(tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    (hf / "hub").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(hf))
    conn = ms.connect()
    yield conn
    conn.close()


class Snapshot:
    """snapshot_download that lands a loadable repo in the hub dir and records the ask."""

    def __init__(self):
        self.asked = []

    def __call__(self, repo_id, **kw):
        self.asked.append(repo_id)
        snap = downloads.hub_dir(repo_id) / "snapshots" / "abc"
        snap.mkdir(parents=True, exist_ok=True)
        for f in ("config.json", "model.safetensors"):
            (snap / f).write_bytes(b"x" * 100)
        return str(snap)


def queued_omnisvg(db, tier="inspect"):
    ms.record(db, ms.Seen(name=OMNI, source="inspect", resolved=OMNI, kind="weights",
                          lane="svg"))
    ms.decide(db, OMNI, "queued", tier=tier)


def on_disk(db, repo):
    fetching.download(repo, snapshot=Snapshot(), text=False, conn=db)
    assert fetching.have(repo, db)


def test_the_runner_base_is_a_requirement_of_each_omnisvg_size():
    assert BASE in fetching.requires(OMNI)
    assert "Qwen/Qwen2.5-VL-7B-Instruct" in fetching.requires("OmniSVG/OmniSVG1.1_8B")
    assert fetching.runner_bases("org/unrelated") == []


def test_a_candidate_fetched_this_run_brings_its_base(db):
    queued_omnisvg(db)
    snap = Snapshot()
    done = fetching.run(db, {OMNI: 9 * GIB, BASE: 7 * GIB}, snapshot=snap, free=FREE)
    assert snap.asked == [OMNI, BASE]
    assert fetching.missing(OMNI, db) == []
    assert any(d["repo"] == BASE and d["ok"] for d in done)


def test_a_candidate_already_on_disk_gets_its_missing_base(db):
    queued_omnisvg(db, tier="screen")
    on_disk(db, OMNI)
    snap = Snapshot()
    fetching.run(db, {BASE: 7 * GIB}, snapshot=snap, free=FREE)
    assert snap.asked == [BASE]
    assert fetching.missing(OMNI, db) == []


def test_a_base_past_the_budget_is_not_fetched_and_the_candidate_waits_on_it(db):
    queued_omnisvg(db, tier="screen")
    on_disk(db, OMNI)
    snap = Snapshot()
    done = fetching.run(db, {BASE: 7 * GIB}, snapshot=snap, free=FREE, budget=4 * GIB)
    assert snap.asked == []
    (row,) = [d for d in done if d["repo"] == BASE]
    assert not row["ok"] and "budget" in row["why"]
    verdict = db.execute("SELECT v.outcome, v.reason, v.detail FROM proposals p "
                         "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?",
                         (OMNI,)).fetchone()
    assert verdict["outcome"] == "queued" and verdict["reason"] == reasons.LIMIT
    assert BASE in verdict["detail"]


def test_a_base_of_unknown_size_is_not_fetched(db):
    queued_omnisvg(db, tier="screen")
    on_disk(db, OMNI)
    snap = Snapshot()
    done = fetching.run(db, snapshot=snap, free=FREE, sizer=lambda repo: -1)
    assert snap.asked == []
    (row,) = [d for d in done if d["repo"] == BASE]
    assert not row["ok"] and "size" in row["why"]


def test_a_candidate_waiting_on_its_base_is_not_screened(db):
    queued_omnisvg(db, tier="screen")
    on_disk(db, OMNI)
    row = {"name": OMNI, "lane": "svg", "attaches_to": ""}
    (got,) = screen.plan([row], missing=lambda m: fetching.missing(m, db))
    assert got["state"] == screen.WAITING and BASE in got["why_not"]


def test_with_its_base_on_disk_the_candidate_is_ready(db):
    on_disk(db, OMNI)
    on_disk(db, BASE)
    row = {"name": OMNI, "lane": "svg", "attaches_to": ""}
    (got,) = screen.plan([row], missing=lambda m: fetching.missing(m, db))
    assert got["state"] == screen.READY
