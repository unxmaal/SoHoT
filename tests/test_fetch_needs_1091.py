"""A candidate's needs are fetched under the budget and disk floor, and a full GGUF does not need its base. #1091."""
from __future__ import annotations

import json

from harness import downloads, fetching, gguf, reasons
from harness import memory_store as ms
from test_context import write_gguf

GIB = fetching.GIB
QWOPUS = "Jackrong/Qwopus3.6-27B-v2-MTP-GGUF"
BASE = "Qwen/Qwen3.6-27B"


def _needs(dep_gib, *, budget_gib=None, spent_gib=0, free_gib=900, floor_gib=0):
    fetched = []
    done, cost, waiting = fetching._fetch_needs(
        "org/M", ["org/tokenizer"], bases=[], sizes={"org/tokenizer": int(dep_gib * GIB)}, sizer=lambda r: -1,
        budget=None if budget_gib is None else int(budget_gib * GIB), spent=int(spent_gib * GIB),
        free=int(free_gib * GIB), floor=int(floor_gib * GIB), fetch=fetched.append)
    return fetched, done, cost, waiting


def test_a_need_over_the_remaining_budget_is_skipped_for_the_budget():
    fetched, (row,), cost, waiting = _needs(52, budget_gib=40, spent_gib=16)
    assert fetched == [] and cost == 0
    assert not row["ok"] and "budget" in row["why"] and "16.0 GiB already fetched" in row["why"]
    assert waiting[0] == reasons.LIMIT


def test_a_need_that_would_leave_the_disk_under_its_floor_is_refused():
    fetched, (row,), cost, waiting = _needs(52, free_gib=80, floor_gib=50)
    assert fetched == [] and cost == 0
    assert not row["ok"] and "floor" in row["why"]
    assert waiting[0] == reasons.MACHINE


def test_a_fetched_need_counts_against_the_budget():
    fetched, (row,), cost, _ = _needs(2, budget_gib=40, spent_gib=16)
    assert fetched == ["org/tokenizer"] and row["ok"] and cost == 2 * GIB == row["bytes"]


def _qwopus(conn, attaches_to=""):
    ms.record(conn, ms.Seen(name=QWOPUS, source="t", resolved=QWOPUS, kind="weights", lane="code"))
    conn.execute("UPDATE proposals SET library = 'transformers', card_tags = ?, attaches_to = ? WHERE name = ?",
                 (json.dumps(["transformers", "gguf", "llama.cpp", "lora"]), attaches_to, QWOPUS))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (QWOPUS,)).fetchone()[0]
    conn.execute("INSERT INTO lineage (proposal_id, parent, kind) VALUES (?, ?, 'adapter')", (pid, BASE))
    conn.commit()


def _on_disk(conn, general_type):
    path = gguf.models_dir() / "Qwopus3.6-27B-v2-MTP-Q4_K_M.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_gguf(path, {"general.type": general_type, "general.architecture": "qwen35"})
    downloads.record(conn, QWOPUS, downloads.GGUF, path, file=path.name)


def test_a_full_gguf_does_not_need_its_adapter_lineage_parent():
    conn = ms.connect()
    try:
        _qwopus(conn)
        assert fetching.requires(QWOPUS, conn) == []
        _on_disk(conn, "model")
        assert fetching.requires(QWOPUS, conn) == []
        assert fetching.missing(QWOPUS, conn) == []
    finally:
        conn.close()


def test_a_lora_gguf_needs_its_base():
    conn = ms.connect()
    try:
        _qwopus(conn, attaches_to="lora")
        assert fetching.requires(QWOPUS, conn) == [BASE]
        _on_disk(conn, "adapter")
        assert fetching.requires(QWOPUS, conn) == [BASE]
    finally:
        conn.close()


def test_the_header_of_the_file_on_disk_outranks_the_card():
    conn = ms.connect()
    try:
        _qwopus(conn, attaches_to="lora")
        _on_disk(conn, "model")
        assert fetching.requires(QWOPUS, conn) == []
    finally:
        conn.close()
