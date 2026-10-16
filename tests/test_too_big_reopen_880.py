"""A too-big refusal judged against a smaller ceiling is re-inspected, never left on a stale size. #880."""
import argparse
import types

import pytest

from harness import inspect as ins
from harness import live_audit
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.memory_store.migrations import prose

GIB = 1024 ** 3
REPO = "unsloth/Qwen3.6-27B-GGUF"
STALE = "too-big: smallest weight it names is 398.1 GiB, over the 22 GiB ceiling"
HERE = types.SimpleNamespace(refuses=lambda runtime: "", runtimes=("cpu", "llamacpp", "mlx"))


def _quants() -> dict:
    """Every quant of one 27B as single files, BF16 as split shards, plus a projector and an imatrix."""
    files = [("Qwen3.6-27B-Q2_K.gguf", 10.1), ("Qwen3.6-27B-Q3_K_M.gguf", 12.9),
             ("Qwen3.6-27B-Q4_K_M.gguf", 15.7), ("Qwen3.6-27B-Q5_K_M.gguf", 18.4),
             ("Qwen3.6-27B-Q6_K.gguf", 21.3), ("Qwen3.6-27B-Q8_0.gguf", 27.5),
             ("BF16/Qwen3.6-27B-BF16-00001-of-00002.gguf", 26.0),
             ("BF16/Qwen3.6-27B-BF16-00002-of-00002.gguf", 25.6),
             ("mmproj-BF16.gguf", 0.9), ("imatrix_unsloth.gguf_file", 0.01),
             ("README.md", 0.0001)]
    return {"id": REPO, "pipeline_tag": "text-generation", "tags": ["gguf", "qwen3"],
            "siblings": [{"rfilename": n, "size": int(g * GIB)} for n, g in files]}


def test_a_multi_quant_listing_is_sized_at_its_smallest_quant_not_the_repo_total():
    card = _quants()
    total = sum(s["size"] for s in card["siblings"])
    assert total > 150 * GIB
    fits = ins.inspect_model(REPO, data=card, ceiling=22 * GIB, machine=HERE)
    assert fits.verdict == "fits"
    assert fits.largest == int(15.7 * GIB)
    big = ins.inspect_model(REPO, data=card, ceiling=8 * GIB, machine=HERE)
    assert big.verdict == "too-big"
    assert ins.until_of(big) == "ceiling_gb:>10.1"
    assert big.ceiling == 8 * GIB


def _see(conn, name):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights",
                            registry=ms.HUGGINGFACE, lane="code"))


def _decline(conn, name, ceiling_gb, until="ceiling_gb:>398.1", detail=STALE):
    _see(conn, name)
    ms.decide(conn, name, "declined", tier=ms.INSPECT, reason="machine", until=until,
              detail=detail, size_bytes=int(398.1 * GIB), ceiling_gb=ceiling_gb)


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def test_the_inspect_writer_records_the_ceiling_it_judged_against(monkeypatch):
    card = _quants()
    conn = ms.connect()
    try:
        _see(conn, REPO)
    finally:
        conn.close()
    monkeypatch.setattr(discover_cmd, "resolve_registry",
                        lambda name, client, model=None: (ms.HUGGINGFACE, card))
    real = ins.inspect_model
    monkeypatch.setattr(ins, "inspect_model",
                        lambda repo, data=None, **kw: real(repo, data=data, ceiling=8 * GIB, machine=HERE))
    from harness import cli
    assert cli.main(["discover", "--inspect", "--repos", REPO]) == 0
    conn = ms.connect()
    try:
        row = conn.execute("SELECT v.outcome, v.ceiling_gb, v.until FROM proposals p "
                           "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?",
                           (REPO,)).fetchone()
    finally:
        conn.close()
    assert (row["outcome"], row["ceiling_gb"], row["until"]) == ("declined", 8.0, "ceiling_gb:>10.1")


def test_a_refusal_judged_against_a_smaller_ceiling_is_stale(store):
    _decline(store, "org/stale", 22.0)
    _decline(store, "org/current", 66.0, until="ceiling_gb:>140.0")
    _decline(store, "org/unrecorded", None)
    _see(store, "org/source")
    ms.decide(store, "org/source", "declined", tier=ms.INSPECT, reason="machine",
              detail="too-big: source tree is 900 MB, which is weights in git", ceiling_gb=22.0)
    assert [r["name"] for r in ms.stale_too_big(store, 66.0)] == ["org/stale"]
    assert ms.stale_too_big(store, 22.5) == []


def test_requeue_hands_a_stale_refusal_back_to_inspect_once(store):
    _decline(store, "org/stale", 22.0)
    assert ms.requeue_stale_too_big(store, 66.0) == ["org/stale"]
    assert store.execute("SELECT state FROM proposals WHERE name = ?", ("org/stale",)).fetchone()[0] == "queued"
    assert "org/stale" in ms.pending(store, screened=False)
    assert ms.requeue_stale_too_big(store, 66.0) == []


def test_the_migration_lifts_the_ceiling_out_of_the_prose(store):
    _decline(store, "org/old", None)
    _decline(store, "org/ds4", None, detail="too-big: x.gguf: 70.0 GiB resident, over the 66 GiB ceiling")
    prose._lift_ceilings_out_of_prose(store)
    got = dict(store.execute("SELECT p.name, v.ceiling_gb FROM proposals p "
                             "JOIN verdicts v ON v.id = p.state_verdict_id").fetchall())
    assert got == {"org/old": 22.0, "org/ds4": 66.0}


def test_the_audit_fails_on_a_stale_too_big_verdict(store):
    assert live_audit._too_big_ceiling_current(store, 66.0) == []
    _decline(store, "org/stale", 22.0)
    bad = live_audit._too_big_ceiling_current(store, 66.0)
    assert len(bad) == 1 and "org/stale (22 GiB)" in bad[0]
    assert "too_big_ceiling_current" in live_audit.CHECKS


def test_the_loop_requeues_stale_refusals_before_its_inspect_step(monkeypatch):
    seen = []

    class Stop(Exception):
        pass

    def fake_discover(sub):
        if getattr(sub, "inspect", False):
            seen.append("inspect")
            raise Stop
        return 0

    monkeypatch.setattr(loop_cmd, "_reopen_stale_too_big", lambda: seen.append("reopen") or [])
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", fake_discover)
    with pytest.raises(Stop):
        loop_cmd._run_loop_held(argparse.Namespace(run=True, lane=""))
    assert seen == ["reopen", "inspect"]


def test_a_dry_run_loop_requeues_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(loop_cmd, "_reopen_stale_too_big", lambda: called.append(1) or [])
    monkeypatch.setattr(loop_cmd.discover_cmd, "cmd_discover", lambda sub: 0)
    loop_cmd._run_loop_held(argparse.Namespace(run=False, lane=""))
    assert called == []
