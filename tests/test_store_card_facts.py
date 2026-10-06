"""A model card's facts are columns and lineage rows written by inspect. #414.

The description stays as prose for the judge. Every reader that used to parse
it back (rank's lineage regex, is_attachment over the description, the runtime
regex, the relane migration's task regex) reads the stored fields instead.
"""
import pytest

from harness import cli, fetching, rank, screen
from harness import inspect as ins
from harness import machine as _machine
from harness import memory_store as ms
from harness.memory import Accelerator

ADAPTER = {"pipeline_tag": "text-to-image", "library_name": "diffusers",
           "tags": ["text-to-image", "anime", "lora",
                    "base_model:adapter:black-forest-labs/FLUX.1-dev"],
           "siblings": [{"rfilename": "a.safetensors", "size": 200 * 1024 ** 2}]}
QUANT = {"pipeline_tag": "text-generation", "library_name": "vllm",
         "tags": ["qwen2", "text-generation",
                  "base_model:finetune:Qwen/Qwen2.5-7B",
                  "base_model:quantized:Qwen/Qwen2.5-7B-Instruct"],
         "siblings": [{"rfilename": "m.safetensors", "size": 4 * 1024 ** 3}]}


@pytest.fixture
def mac(monkeypatch):
    m = _machine.Machine(frozenset({"mlx", "cpu"}),
                         Accelerator("unified", 32.0, 25.0, "Mac14,12"))
    monkeypatch.setattr(_machine, "detect", lambda *a, **k: m)
    return m


def _inspect(monkeypatch, cards: dict) -> None:
    """Run the real inspect command over recorded cards, no network."""
    monkeypatch.setattr(ins, "hf_model", lambda m, fetch=None: cards[m])
    args = type("A", (), {"repos": list(cards), "from_store": False, "top": 10,
                          "budget": 10, "shard": "", "judge": False,
                          "json": False})()
    for name in cards:
        conn = ms.connect()
        ms.record(conn, ms.Seen(name=name, source="t",
                                registry=ms.HUGGINGFACE, resolved=name))
        conn.close()
    assert cli._report_inspect(args) == 0


def test_inspect_writes_the_card_as_columns_and_lineage(monkeypatch, mac):
    _inspect(monkeypatch, {"org/style-lora": ADAPTER, "org/q-awq": QUANT})
    conn = ms.connect()
    try:
        p = {r["name"]: dict(r) for r in conn.execute(
            "SELECT * FROM proposals")}
        assert p["org/style-lora"]["hf_task"] == "text-to-image"
        assert p["org/style-lora"]["library"] == "diffusers"
        assert p["org/style-lora"]["attaches_to"] == "lora"
        assert p["org/style-lora"]["card_read"] == "card"
        assert p["org/style-lora"]["lane_source"] == "card"
        assert "anime" in p["org/style-lora"]["card_tags"]
        assert p["org/q-awq"]["runtime_needed"] == "vllm"
        assert p["org/q-awq"]["attaches_to"] == ""
        got = ms.parents_of(conn, ["org/style-lora", "org/q-awq"])
        assert got["org/style-lora"] == [("black-forest-labs/FLUX.1-dev",
                                          "adapter")]
        assert got["org/q-awq"] == [("Qwen/Qwen2.5-7B", "finetune"),
                                    ("Qwen/Qwen2.5-7B-Instruct", "quantized")]
        # The prose is still there, for the judge.
        assert "adapter of" in p["org/style-lora"]["description"]
    finally:
        conn.close()


def test_reinspecting_replaces_lineage_rather_than_merging(monkeypatch, mac):
    _inspect(monkeypatch, {"org/q-awq": QUANT})
    _inspect(monkeypatch, {"org/q-awq": {**QUANT, "tags": ["qwen2"]}})
    conn = ms.connect()
    try:
        assert ms.parents_of(conn, ["org/q-awq"])["org/q-awq"] == []
    finally:
        conn.close()


def test_an_adapter_is_an_attachment_from_the_column(tmp_path):
    """base_model:adapter:X with no lora/adapter word anywhere else on the
    card: the relation kind alone makes it an attachment."""
    card = ins.card_facts({"pipeline_tag": "text-to-image",
                           "tags": ["base_model:adapter:org/base"]})
    assert card.attaches_to == "adapter"
    conn = ms.connect(tmp_path / "s.db")
    try:
        for name in ("org/innocuous", "org/plain"):
            ms.record(conn, ms.Seen(name=name, source="t", lane="image",
                                    registry=ms.HUGGINGFACE, resolved=name))
            ms.decide(conn, name, "queued", tier=ms.INSPECT, detail="fits")
        ms.set_card(conn, "org/innocuous", card)
        ms.set_card(conn, "org/plain", ins.card_facts(
            {"pipeline_tag": "text-to-image", "tags": ["base_model:org/base"]}))
        rows = ms.judgeable(conn, limit=10)
        ranked = [r["name"] for r in rank.rank(rows, measured_lanes=())]
        assert ranked == ["org/plain"], "the adapter must drop, the plain stay"
        plan = {r["name"]: r for r in screen.plan(rows, missing=lambda n: [])}
        assert "attaches to a model" in plan["org/innocuous"]["why_not"]
        assert "attaches to a model" not in plan["org/plain"]["why_not"]
        fetch_rows = {r["name"]: r for r in fetching.queued(conn,
                                                            needs_lane=False)}
        assert fetch_rows["org/innocuous"]["attaches_to"] == "adapter"
    finally:
        conn.close()


# --- the one-time backfill ---------------------------------------------------

def _old_store(path, rows):
    """A store as schema 31 left it: descriptions and no card columns set."""
    conn = ms.connect(path)
    for name, registry, desc in rows:
        ms.record(conn, ms.Seen(name=name, source="t", registry=registry,
                                resolved=name, description=desc))
    conn.execute("DELETE FROM lineage")
    conn.execute("UPDATE proposals SET hf_task='', library='', card_tags='[]',"
                 " attaches_to='', runtime_needed='', card_read='', "
                 "lane_source=''")
    conn.execute("UPDATE meta SET value='31' WHERE key='schema'")
    conn.commit()
    conn.close()


def test_the_migration_recovers_what_the_description_kept(tmp_path):
    path = tmp_path / "old.db"
    _old_store(path, [
        ("org/lora", ms.HUGGINGFACE, ins.card_description(ADAPTER)),
        ("org/q", ms.HUGGINGFACE, ins.card_description(QUANT)),
        ("org/tool", ms.GITHUB, "a task runner built from scratch, CUDA only"),
    ])
    conn = ms.connect(path)
    try:
        p = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM proposals")}
        assert p["org/lora"]["card_read"] == "description"
        assert p["org/lora"]["hf_task"] == "text-to-image"
        assert p["org/lora"]["attaches_to"] == "lora"
        assert p["org/q"]["library"] == "vllm"
        assert p["org/q"]["runtime_needed"] == "vllm"
        lin = ms.parents_of(conn, ["org/lora", "org/q", "org/tool"])
        assert lin["org/lora"] == [("black-forest-labs/FLUX.1-dev", "adapter")]
        # `built from` never said which kind: that is lost, and recorded ''.
        assert lin["org/q"] == [("Qwen/Qwen2.5-7B", ""),
                                ("Qwen/Qwen2.5-7B-Instruct", "")]
        # A GitHub one-liner is not a card: no lineage, no task from prose.
        assert lin["org/tool"] == [] and p["org/tool"]["hf_task"] == ""
        assert p["org/tool"]["runtime_needed"] == "cuda", (
            "attachment and runtime keep the reading the old readers made")
    finally:
        conn.close()


def test_a_truncated_description_loses_what_was_cut():
    desc = ("task text-generation; tagged " + ", ".join(["x"] * 200))[:300]
    card, lost = ms.card_from_description(desc, True)
    assert card.task == "text-generation" and card.parents == []
    assert "truncated" in lost


def test_the_description_parsers_are_gone_from_the_readers():
    """#414. Each reader's own copy of the grammar is deleted; the only one
    left is the backfill's, which runs once."""
    assert not hasattr(rank, "_LINEAGE") and not hasattr(rank, "_parents")
    assert not hasattr(ms, "_CARD_TASK")
    assert not hasattr(ins, "_SERVED_BY")
