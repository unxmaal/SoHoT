"""#1942: requeue, retract and replay decisions read verdicts.event, sized_by, failure_class and reopen_kind, never the detail sentence."""
import dataclasses
import json

import pytest

from harness import adopt, baseline, coherence, effects, holdout, looks, quants, reasons, variants
from harness import inspect as ins
from harness import memory_store as ms
from harness.memory_store import transitions
from tests.test_futility_lane_too_small_1452 import CH, INC, POWERED, SPLIT, UNPOWERED, _rows

REWORDED = "said another way"
T = 1791000000.0


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _see(conn, name, lane="code", registry=ms.HUGGINGFACE):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights", registry=registry, lane=lane))


def _refused(conn, name, event, detail=REWORDED, sized_by="", lane="code"):
    _see(conn, name, lane)
    return ms.decide(conn, name, "declined", tier=ms.INSPECT, reason=reasons.MACHINE, until="ceiling_gb:>99.0",
                     detail=detail, event=event, sized_by=sized_by)


def test_a_quants_parent_is_freed_by_its_refusals_event_whatever_it_says(conn):
    _refused(conn, "org/big", ins.TOO_BIG)
    _refused(conn, "org/gguf-only", "needs-llamacpp")
    _refused(conn, "org/said-too-big", "", detail="too-big: smallest weight it names is 67.0 GiB")
    _refused(conn, "org/said-needs", "fits", detail="needs-vllm: this machine has none")
    assert quants.unrunnable(conn) == ["org/big", "org/gguf-only"]


def test_a_refusal_sized_by_the_listing_is_requeued_by_its_columns_whatever_it_says(conn):
    _refused(conn, "org/summed", ins.TOO_BIG, sized_by=variants.SIZED_LISTING)
    _refused(conn, "org/variant", ins.TOO_BIG, detail="too-big: smallest weight it names is 223.2 GiB",
             sized_by=variants.SIZED_VARIANT)
    _refused(conn, "org/resident", ins.TOO_BIG, detail="too-big: smallest weight it names is 70.0 GiB",
             sized_by=variants.SIZED_RESIDENT)
    assert [r["name"] for r in ms.sized_by_repo_total(conn)] == ["org/summed"]


def test_a_gguf_sizing_off_its_lane_is_read_from_sized_by_whatever_it_says(conn):
    for name, lane, sized, said in (("org/tts-gguf", "tts", variants.SIZED_GGUF, REWORDED),
                                    ("org/code-gguf", "code", variants.SIZED_GGUF, REWORDED),
                                    ("org/tts-said", "tts", variants.SIZED_VARIANT,
                                     f"fits: {variants.MARK}m.f16.gguf: 0.5 GiB of 1 weight file")):
        _see(conn, name, lane)
        ms.decide(conn, name, "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail=said,
                  event="fits", sized_by=sized)
    assert [r["name"] for r in ms.gguf_sized_off_lane(conn)] == ["org/tts-gguf"]


def test_a_library_tag_refusal_reads_whether_its_last_inspect_named_a_variant_from_sized_by(conn):
    for name, sized, said in (("org/read", variants.SIZED_VARIANT, REWORDED),
                              ("org/tagged", variants.SIZED_LISTING, f"fits: {variants.MARK}x.safetensors")):
        _see(conn, name)
        ms.decide(conn, name, "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail=said, sized_by=sized)
        ms.decide(conn, name, "declined", tier="fetch", reason=reasons.MACHINE, until="runtime:vllm", detail=REWORDED)
    assert [r["name"] for r in ms.runtime_by_library(conn)] == ["org/tagged"]


def test_an_incomplete_copy_is_found_by_its_failure_class_whatever_it_says(conn):
    said = "The cached snapshot at /x is incomplete: 1 file(s) are missing (model.safetensors)"
    for name, cls, detail in (("org/copy", reasons.INCOMPLETE_COPY, REWORDED),
                              ("org/runtime", reasons.LOAD_FAILED_RUNTIME, said)):
        _see(conn, name, "stt")
        ms.decide(conn, name, "declined", tier=ms.SCREEN, reason=reasons.RUNTIME, until="version:mlx-audio>0.5.3",
                  failure_class=cls, detail=detail)
    assert [r["name"] for r in ms.incomplete_copies(conn)] == ["org/copy"]


def test_a_raw_write_that_only_says_retracted_is_not_folded_as_a_reopen(conn):
    for name in ("org/said", "org/kind"):
        _see(conn, name)
        ms.decide(conn, name, "broken", tier=ms.SCREEN, reason=reasons.CANDIDATE, detail="0 of 3")
    ms.decide(conn, "org/kind", "queued", tier=ms.SCREEN, detail=REWORDED, reopen=transitions.RETRACTION,
              reopen_why=REWORDED)
    pid = conn.execute("SELECT id FROM proposals WHERE name = 'org/said'").fetchone()[0]
    vid = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) "
                       "VALUES (?, 'queued', 'screen', 'retracted: our server died', 0)", (pid,)).lastrowid
    conn.execute("UPDATE proposals SET state = 'queued', state_verdict_id = ? WHERE id = ?", (vid, pid))
    conn.commit()
    assert ms.state_audit(conn)["folds_differently"] == [{"name": "org/said", "state": "queued", "folded": "broken"}]


# --- adopt stops ---------------------------------------------------------------------------------------


@pytest.fixture
def code_lane(monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: dataclasses.replace(SPLIT, lane=lane))


def _stop(conn, name, event, detail, plan, outcome="declined", failure_class=""):
    _see(conn, name)
    ms.decide(conn, name, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    vid = transitions._write(conn, pid, name, {
        "outcome": outcome, "tier": ms.ADOPT, "reason": reasons.CANDIDATE, "until": "", "decided_at": T,
        "detail": detail, "failure_class": failure_class, "event": event, "lane": "code"})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(plan), vid))
    conn.commit()
    return vid


def test_coherence_re_decides_a_futility_stop_by_its_event_whatever_it_says(conn, code_lane):
    _stop(conn, "org/reworded", adopt.FUTILITY, f"code: {REWORDED}", UNPOWERED.as_dict())
    _stop(conn, "org/said", "", "code: futility: look 2 at 35/40 holdout cells", UNPOWERED.as_dict())
    assert [c["name"] for c in coherence.lane_bound(conn)] == ["org/reworded"]


def test_the_effect_replay_reads_a_stop_by_its_event_whatever_it_says(conn):
    plan = {"effect": 0.2, "mde": 0.15, "enough": True, "target": 0.8, "power": 0.9}
    fut = _stop(conn, "org/fut", adopt.FUTILITY, f"code: {REWORDED}", plan)
    worse = _stop(conn, "org/worse", adopt.WORSE, f"code: {REWORDED}", plan)
    took = _stop(conn, "org/took", baseline.EVENT, f"code: {REWORDED}", plan, outcome="measured")
    said = _stop(conn, "org/said", "", "code: futility: look 2; significantly worse: 9 lost", plan)
    told = _stop(conn, "org/told", "", f"code: {baseline.SOURCE}: org/told passed", plan, outcome="measured")
    got = {r["id"]: r["why"] for r in effects.replay(conn, {"code": 0.3})}
    assert got[fut].startswith("may change: conditional power rises")
    assert got[worse] == "a significant loss does not depend on the effect"
    assert got[took] == "not decided by the paired gate"
    assert got[said] == "its run could see +0.15, within the lane's +0.30"
    assert got[told] == "a gate win with no dev confirmation waits for a night confirmation run"


# --- writers --------------------------------------------------------------------------------------------


def test_a_futility_look_and_a_significant_loss_name_their_event():
    _, stop = looks.look(_rows(35, lost=20), lane="code", inc_key=INC, ch_key=CH, split=SPLIT,
                         plan=POWERED.as_dict(), alpha=0.05, spent_before=0.0, n=2, spec=CH)
    assert stop.event == adopt.FUTILITY
    rows = _rows(40, lost=20)
    got = adopt.decide("code", {"candidate": INC}, {"candidate": CH}, rows, split=SPLIT)
    assert not got.adopt and got.event == adopt.WORSE
    won = adopt.decide("code", {"candidate": CH}, {"candidate": INC}, rows, split=SPLIT)
    assert won.event == ""


def test_record_writes_the_verdicts_event(conn):
    _see(conn, "org/m")
    vid = adopt.record(conn, adopt.Verdict("code", "inc", "org/m", False, REWORDED, event=adopt.WORSE), spec="org/m")
    assert conn.execute("SELECT event, detail FROM verdicts WHERE id = ?", (vid,)).fetchone()[0] == adopt.WORSE


@pytest.mark.parametrize("fit,sized", [
    (ins.Fit(repo="r", variant="m.gguf: 1 GiB", variant_format=variants.GGUF, smallest=1), variants.SIZED_GGUF),
    (ins.Fit(repo="r", variant="m.safetensors: 1 GiB", variant_format=variants.HF, smallest=1), variants.SIZED_VARIANT),
    (ins.Fit(repo="r", ds4=True, ds4_file="x.gguf", resident=5, smallest=9), variants.SIZED_RESIDENT),
    (ins.Fit(repo="r", ds4=True), ""),
    (ins.Fit(repo="r", largest=9), variants.SIZED_LISTING),
    (ins.Fit(repo="r"), ""),
])
def test_an_inspect_says_what_sized_it(fit, sized):
    assert ins.sized_by(fit) == sized


def test_the_inspect_tier_writes_its_finding_and_sizing_beside_its_sentence(monkeypatch, capsys):
    from harness.commands import discover as discover_cmd
    from tests.test_quants_882 import BASE, GGUF, _pin, _registry
    _pin(monkeypatch)
    monkeypatch.setattr(ins, "hf_get", _registry())
    c = ms.connect()
    _see(c, BASE)
    c.close()
    args = type("A", (), {"repos": [], "from_store": True, "top": 10, "budget": 10,
                          "shard": "", "judge": False, "json": False})()
    assert discover_cmd._report_inspect(args) == 0
    c = ms.connect()
    try:
        got = dict(c.execute("SELECT p.name, v.event || ' ' || v.sized_by FROM proposals p "
                             "JOIN verdicts v ON v.proposal_id = p.id AND v.tier = 'inspect'").fetchall())
    finally:
        c.close()
    assert got == {BASE: f"{ins.TOO_BIG} {variants.SIZED_VARIANT}", GGUF: f"fits {variants.SIZED_GGUF}"}


# --- the backfill ---------------------------------------------------------------------------------------


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v106.py:data:verdicts")
def test_the_backfill_lifts_each_older_sentence_into_its_column_once(conn):
    from harness.memory_store.migrations import v106
    said = {
        "too-big: smallest weight it names is 67.0 GiB, over the 22 GiB ceiling": ("inspect", ""),
        f"too-big: {variants.MARK}m-Q4.gguf: 20.0 GiB of 1 weight file, over the 22 GiB ceiling": ("inspect", ""),
        f"fits: {variants.MARK}model.safetensors: 3.0 GiB of 1 weight file": ("inspect", ""),
        "too-big: x.gguf: 70.0 GiB resident, over the 66 GiB ceiling": ("inspect", ""),
        "needs-llamacpp: depends on GGUF weights": ("inspect", ""),
        "needs training or new weights, which this harness does not do": ("inspect", ""),
        "fits": ("inspect", ""),
        "fits: said before its writer named it": ("inspect", "", ins.TOO_BIG),
        "code: futility: look 2 at 35/40 holdout cells": ("adopt", ""),
        "code: won the holdout (verdict 9), but its confirmation stopped for futility: look 1": ("adopt", ""),
        "code: lane too small, needs 300 (futility: look 2)": ("adopt", reasons.LANE_TOO_SMALL),
        "code: does not beat the incumbent; significantly worse: 9 lost": ("adopt", ""),
        f"code: {baseline.SOURCE}: org/x passed 3 of 4": ("adopt", ""),
        "the installed runtime could not load it: The cached snapshot at /x is incomplete: "
        "1 file(s) are missing (model.safetensors)": ("screen", reasons.LOAD_FAILED_RUNTIME),
        "retracted: our server died": ("screen", ""),
        "downloaded": ("fetch", ""),
    }
    ids = {}
    for i, (detail, (tier, cls, *event)) in enumerate(said.items()):
        name = f"org/m{i}"
        _see(conn, name)
        pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
        ids[detail] = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, failure_class, event, "
                                   "decided_at) VALUES (?, 'declined', ?, ?, ?, ?, 0)",
                                   (pid, tier, detail, cls, "".join(event))).lastrowid
    v106.data(conn)
    v106.data(conn)
    got = {d: tuple(conn.execute("SELECT event, sized_by, failure_class, reopen_kind FROM verdicts WHERE id = ?",
                                 (i,)).fetchone()) for d, i in ids.items()}
    assert list(got.values()) == [
        (ins.TOO_BIG, variants.SIZED_LISTING, "", ""),
        (ins.TOO_BIG, variants.SIZED_GGUF, "", ""),
        ("fits", variants.SIZED_VARIANT, "", ""),
        (ins.TOO_BIG, variants.SIZED_RESIDENT, "", ""),
        ("needs-llamacpp", "", "", ""),
        ("", "", "", ""),
        ("fits", "", "", ""),
        (ins.TOO_BIG, "", "", ""),
        (adopt.FUTILITY, "", "", ""),
        (adopt.FUTILITY, "", "", ""),
        ("", "", reasons.LANE_TOO_SMALL, ""),
        (adopt.WORSE, "", "", ""),
        (baseline.EVENT, "", "", ""),
        ("", "", reasons.INCOMPLETE_COPY, ""),
        ("", "", "", transitions.RETRACTION),
        ("", "", "", ""),
    ]
