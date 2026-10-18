"""An attachment is a whole tag the listing agrees with, never a substring of one. #949."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import fetching, inspect as ins, live_audit, reasons, screen
from harness import memory_store as ms
from tests.test_runner_base_weights import Snapshot, db  # noqa: F401

CARDS = Path(__file__).parent / "fixtures" / "registry" / "attachments_949"
GIB = fetching.GIB


def _card(repo: str) -> dict:
    return json.loads((CARDS / f"{repo.replace('/', '_')}.json").read_text(encoding="utf-8"))


def _words(data: dict) -> list[str]:
    return [data.get("pipeline_tag") or "", data.get("library_name") or "",
            *[t for t in data["tags"] if not t.lower().startswith("base_model")]]


@pytest.mark.parametrize("repo", ["Boogu/Boogu-Image-0.1-Edit", "inclusionAI/VISTA-9B", "Hcompany/Holo-3.1-0.8B",
                                  "FINAL-Bench/Darwin-4B-David", "mindlab-research/Macaron-V1-Preview-749B",
                                  "mlx-community/LongCat-Flash-Lite-Sparse-4bit"])
def test_a_tag_that_merely_contains_a_word_is_no_attachment(repo):
    assert screen.is_attachment(_words(_card(repo))) == ""


@pytest.mark.parametrize("repo", ["oumoumad/LTX-2.3-22b-IC-LoRA-Outpaint", "neuralvfx/Z-Image-SAM-ControlNet"])
def test_a_real_adapter_is_still_one_by_its_listing(repo):
    assert ins.card_facts(_card(repo)).attaches_to in screen.ADAPTER_KINDS + ("controlnet",)


@pytest.mark.parametrize("repo", ["Jackrong/Qwopus3.5-9B-Coder-GGUF", "black-forest-labs/FLUX.2-klein-9B",
                                  "Boogu/Boogu-Image-0.1-Edit", "realrebelai/FastH3-V2_GGUFs",
                                  "mindlab-research/Macaron-V1-Preview-749B"])
def test_a_full_listing_outweighs_a_weight_word(repo):
    assert ins.card_facts(_card(repo)).attaches_to == ""


def test_an_adapter_only_listing_is_an_attachment_and_a_weightless_tool_is_too():
    files = [{"rfilename": "adapter_config.json", "size": 700},
             {"rfilename": "adapter_model.safetensors", "size": 40 * 2**20}]
    assert screen.is_attachment(["text-generation", "peft"], files) == "adapter"
    assert screen.is_attachment(["video", "browser"], []) == "browser"
    assert screen.is_attachment(["video", "browser"], [{"rfilename": "model.safetensors", "size": GIB}],
                                {"model_type": "x"}) == ""


def test_a_name_still_names_its_adapter():
    assert screen.is_attachment("LiconStudio/Ltx2.3-VBVR-lora-I2V") == "lora"
    assert screen.is_attachment("Boogu/Boogu-Image-0.1-Edit") == ""


def _seed(db, repo, lane, attaches_to, card_read="description", declined=True):
    ms.record(db, ms.Seen(name=repo, source="t", resolved=repo, kind="weights", lane=lane,
                          registry=ms.HUGGINGFACE))
    db.execute("UPDATE proposals SET attaches_to = ?, card_read = ?, card_tags = ? WHERE name = ?",
               (attaches_to, card_read, json.dumps(_card(repo)["tags"]), repo))
    ms.set_size(db, repo, GIB)
    ms.decide(db, repo, "queued", tier="inspect", detail="fits", size_bytes=GIB, reason=reasons.CANDIDATE)
    if declined:
        ms.decide(db, repo, "declined", tier="fetch", reason=reasons.CANDIDATE,
                  detail=f"{attaches_to} in its own card: this attaches to a model rather than being one, "
                         f"and no lane can run it alone")
    db.commit()


def test_rederive_requeues_a_model_and_keeps_an_adapter_declined(db):
    _seed(db, "Boogu/Boogu-Image-0.1-Edit", "image", "gui", card_read="card")
    _seed(db, "Jackrong/Qwopus3.5-9B-Coder-GGUF", "code", "lora")
    _seed(db, "oumoumad/LTX-2.3-22b-IC-LoRA-Outpaint", "video", "lora")
    _seed(db, "mindlab-research/Macaron-V1-Preview-749B", "code", "lora", card_read="card", declined=False)
    assert len(ms.stale_attachments(db)) == 4
    got = ms.rederive_attachments(db, read=_card)
    state = dict(db.execute("SELECT name, state FROM proposals").fetchall())
    assert got["read"] == 4
    assert sorted(got["requeued"]) == ["Boogu/Boogu-Image-0.1-Edit", "Jackrong/Qwopus3.5-9B-Coder-GGUF"]
    assert state["Boogu/Boogu-Image-0.1-Edit"] == "queued"
    assert state["oumoumad/LTX-2.3-22b-IC-LoRA-Outpaint"] == "declined"
    assert {c["name"]: c["now"] for c in got["changed"]}["mindlab-research/Macaron-V1-Preview-749B"] == ""
    assert ms.stale_attachments(db) == []
    assert ms.rederive_attachments(db, read=_card)["read"] == 0


def test_an_unreadable_card_is_left_for_the_next_sweep(db):
    _seed(db, "Boogu/Boogu-Image-0.1-Edit", "image", "gui")

    def gone(repo):
        raise ins.Gone(f"{repo}: the registry has no model by that name")
    got = ms.rederive_attachments(db, read=gone)
    assert got["read"] == 0 and len(got["gone"]) == 1
    assert len(ms.stale_attachments(db)) == 1


def test_the_audit_counts_attachments_no_card_reading_gives(db):
    _seed(db, "inclusionAI/VISTA-9B", "image", "gui", card_read="card")
    assert live_audit._attachment_by_tag(db, None) == ([], ["inclusionAI/VISTA-9B: attaches_to gui (card)"])
    ms.rederive_attachments(db, read=_card)
    assert live_audit._attachment_by_tag(db, None) == ([], [])


def test_a_full_model_no_lane_runs_is_queued_as_a_runner_gap(db, monkeypatch):
    monkeypatch.setattr(fetching.rank, "unrunnable", lambda row, m=None: "")
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    repo = "realrebelai/FastH3-V2_GGUFs"
    ms.record(db, ms.Seen(name=repo, source="t", resolved=repo, kind="weights", lane="video",
                          registry=ms.HUGGINGFACE))
    ms.set_card(db, repo, ins.card_facts(_card(repo)))
    ms.set_size(db, repo, 18 * GIB)
    ms.decide(db, repo, "queued", tier="inspect", detail="fits", size_bytes=18 * GIB, reason=reasons.CANDIDATE)
    snap = Snapshot()
    done = fetching.run(db, limit=5, free=900 * GIB, snapshot=snap,
                        listing=lambda r: _card(repo)["siblings"])
    last = db.execute("SELECT v.outcome, v.reason FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                      "WHERE p.name = ? ORDER BY v.id DESC LIMIT 1", (repo,)).fetchone()
    assert snap.asked == [] and not done[0]["ok"]
    assert (last["outcome"], last["reason"]) == ("queued", reasons.HARNESS)


def test_the_loop_rereads_every_attachment_once_then_only_stale_ones(monkeypatch):
    from harness import heartbeat
    from harness.commands import loop as loop_cmd
    asked = []

    def fake(conn, read=None, every=False):
        asked.append(every)
        return {"read": 0, "changed": [], "requeued": [], "unread": [], "gone": []}
    monkeypatch.setattr(ms, "rederive_attachments", fake)
    heartbeat.start()
    loop_cmd._rederive_attachments()
    heartbeat.finish(0)
    heartbeat.start()
    loop_cmd._rederive_attachments()
    heartbeat.finish(0)
    assert asked == [True, False]


def test_lora_files_in_a_checkpoints_folder_are_not_a_comfyui_model():
    files = [{"rfilename": f"_archive/checkpoints/krea2_turbo_4step_rank_64_lora_chk0000{i}000.safetensors",
              "size": 440_000_000} for i in range(4, 9)]
    assert screen.is_attachment(["text-to-image", "lora"], files) == "lora"
