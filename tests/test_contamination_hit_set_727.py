"""#727 follow-up: HIT is the value its committed calibration probes derive, and the lane probe runs again."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import contamination as ct
from harness import knobs
from harness import memory_store as ms

PROBES = Path(__file__).resolve().parent.parent / "evals" / "contamination" / "probes.jsonl"


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _load(conn):
    rows = [json.loads(line) for line in PROBES.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        ms.record_probe(conn, model=r["model"], lane=r["lane"], case_id=r["case_id"], family=r["family"],
                        outcome=r["outcome"], overlap=r["overlap"], at=r["at"])
    return rows


def test_the_shipped_hit_is_the_value_its_calibration_probes_derive(store):
    rows = _load(store)
    assert {r["model"] for r in rows} == {"sohot-code", "sohot-decide", "sohot-extract"}
    got = ct.calibrate(store)
    assert got["status"] == "derived" and got["derived"] == ct.HIT == 0.25 and got["agrees"] is True
    for m in got["models"]:
        clean = [r["overlap"] for r in rows if r["model"] == m["model"] and r["family"] == "clean"]
        assert sum(o >= ct.HIT for o in clean) <= (1 - ct.CLEAN_SHARE) * len(clean), m["model"]
    assert knobs.KNOBS["contamination_hit"].default() == ct.HIT
    assert "probes.jsonl" in knobs.KNOBS["contamination_hit"].note


def test_an_errored_newest_probe_supersedes_an_older_miss(store):
    ms.record_probe(store, model="m", lane=ct.CALIBRATION, case_id="clean-000", family="clean",
                    outcome="miss", overlap=0.9, at=1.0)
    ms.record_probe(store, model="m", lane=ct.CALIBRATION, case_id="clean-000", family="clean",
                    outcome="error", overlap=None, at=2.0)
    ms.record_probe(store, model="m", lane=ct.CALIBRATION, case_id="clean-001", family="clean",
                    outcome="miss", overlap=0.0, at=2.0)
    assert ct._newest(store) == {"m": {"clean": [0.0]}}


def test_a_lane_probe_reads_the_lanes_cases(store, monkeypatch):
    from harness.commands import benchmarks as cmd
    asked = []
    monkeypatch.setattr(ct, "gateway_ask", lambda base: lambda model, prompt: asked.append(model) or "no")
    args = type("A", (), {"lane": "decide", "probe": ["m"], "passages": False, "limit": 3, "gateway": "http://gw"})()
    assert cmd._probe(args, store) == 0
    got = store.execute("SELECT lane, COUNT(*) FROM contamination_probes GROUP BY lane").fetchall()
    assert [tuple(r) for r in got] == [("decide", 3)]
