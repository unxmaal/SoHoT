"""A lane's default is a stored spec the lane can serve, read from the store rather than from `/` and `:` in a key. #1122."""
from __future__ import annotations

import pytest

from harness import candidates, winners
from harness import memory_store as ms

HF = "mlx-community/Qwen3-4B-Instruct-2507-4bit"


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def own(*keys):
    return {k: k for k in keys}


def test_an_hf_id_and_an_engine_spec_can_be_an_alias_lanes_default(conn, store_run, sat_exam):
    store_run("w", "web", {"q3-4b": {"pass_rate": 0.5}, HF: {"pass_rate": 1.0}}, specs=own("q3-4b", HF))
    store_run("c", "code", {"q3-4b": {"pass_rate": 0.5}, "llamacpp:O": {"pass_rate": 1.0}},
              specs=own("q3-4b", "llamacpp:O"))
    got = winners.from_receipts(conn)
    assert (got["web"]["candidate"], got["code"]["candidate"]) == (HF, "llamacpp:O")


def test_a_method_is_a_default_only_on_a_lane_it_applies_to(conn, store_run, sat_exam):
    summary = {"best-of-3/llamacpp:O": {"pass_rate": 1.0}, "llamacpp:O": {"pass_rate": 0.5}}
    specs = {"best-of-3/llamacpp:O": "best-of:3:llamacpp:O", "llamacpp:O": "llamacpp:O"}
    store_run("c", "code", summary, specs=specs)
    store_run("e", "extract", summary, specs=specs)
    got = winners.from_receipts(conn)
    assert (got["code"]["candidate"], got["extract"]["candidate"]) == ("best-of-3/llamacpp:O", "llamacpp:O")


def test_a_control_and_a_workflow_are_never_a_default(conn, store_run, sat_exam):
    store_run("c", "code", {"neutral/llamacpp:O": {"pass_rate": 1.0}, "repair/q3-4b": {"pass_rate": 1.0},
                            "q3-4b": {"pass_rate": 0.2}},
              specs={"neutral/llamacpp:O": "neutral:llamacpp:O", "repair/q3-4b": "repair:q3-4b", "q3-4b": "q3-4b"})
    assert winners.from_receipts(conn)["code"]["candidate"] == "q3-4b"
    assert winners.from_receipts(conn, plain_only=False)["code"]["candidate"] != "q3-4b"


def test_a_key_the_receipt_does_not_name_is_read_from_its_candidates_row_or_dropped(conn, store_run, sat_exam):
    candidates.ensure(conn, "llamacpp:Z", key="zkey", lane="code")
    conn.commit()
    store_run("c", "code", {"zkey": {"pass_rate": 0.9}, "nokey": {"pass_rate": 1.0}, "q3-4b": {"pass_rate": 0.5}},
              specs=own("q3-4b"))
    assert winners.from_receipts(conn)["code"]["candidate"] == "zkey"


def test_an_hf_id_that_beat_the_served_default_is_a_disagreement(conn, store_run, sat_exam, monkeypatch):
    monkeypatch.setattr(winners, "typed", lambda: {"extract": "local-large"})
    store_run("x", "extract", {"local-large": {"pass_rate": 0.5}, HF: {"pass_rate": 1.0, "median_s": 5.0},
                               "repair/q3-4b": {"pass_rate": 1.0, "median_s": 1.0}},
              specs={**own("local-large", HF), "repair/q3-4b": "repair:q3-4b"})
    assert winners.beaten_in(conn)["extract"]["candidate"] == HF
    assert [(r["modality"], r["measured"]) for r in winners.disagreements(conn)] == [("extract", HF)]
