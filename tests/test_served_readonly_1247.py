"""What a lane serves is looked up without writing, so read-only callers work on a mode=ro store. #1247."""
import hashlib

import pytest

from harness import adopt, candidates, gateway, live_audit, report, reverify, runs, screen, sweeps, winners
from harness import memory_store as ms
from tests import conftest

NOW = 1_800_000_000.0
MAC = gateway.REPO / "gateway" / "config.yaml"
M2 = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
      "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64", "memory_gb": 32.0,
      "accelerator": "unified 32GB", "runtimes": "cpu,mlx", "ceiling_gb": 22.0,
      "versions": {"mlx-lm": "0.28.0", "llama.cpp": "6500"}}


@pytest.fixture
def path(tmp_path, monkeypatch):
    conftest.stand_in_machine(monkeypatch, M2)
    p = tmp_path / "d.db"
    conn = ms.connect(p)
    ms.remember_machine(conn, M2)
    rid = runs.record(conn, "runs/r1-code", {
        "receipt": {"modality": "code", "tier": "measure"}, "environment": {"versions": M2["versions"]},
        "specs": {"q3-4b": "q3-4b"}, "generated": "2026-10-01T10:00:00",
        "rows": [{"candidate": "q3-4b", "case_id": f"c{i}", "passed": i < 3, "seconds": 1.0} for i in range(5)]},
        at=NOW - 86400)
    assert rid
    adopt.record(conn, adopt.Verdict("code", "q3-4b", "q3-8b", True, "won"))
    for lane, spec in winners.typed().items():
        candidates.ensure(conn, screen.candidate_for(lane, spec) or spec, lane=lane)
    conn.close()
    return p


def _read_only(p):
    return live_audit.open_readonly(p)


def _bytes(p):
    return hashlib.sha256(b"".join(f.read_bytes() for f in sorted(p.parent.glob(p.name + "*")))).hexdigest()


def test_served_answers_every_lane_on_a_read_only_store(path):
    rw = ms.connect(path)
    want_served, want_ids = reverify.served(rw), winners.served_ids(rw)
    rw.close()
    ro = _read_only(path)
    try:
        got_served, got_ids = reverify.served(ro), winners.served_ids(ro)
    finally:
        ro.close()
    assert want_served and got_served == want_served
    assert want_ids and got_ids == want_ids
    assert got_served["code"]["spec"] == "q3-8b" and got_served["code"]["incumbent"] == "q3-4b"


def test_a_served_lookup_makes_no_writes(path):
    conn = ms.connect(path)
    before, file_before = conn.total_changes, _bytes(path)
    candidates.served(conn, "q3-4b", lane="code")
    reverify.served(conn)
    winners.served_ids(conn)
    report.lanes_state(conn, now=NOW)
    sweeps.plan(conn, now=NOW)
    sweeps.check(conn, now=NOW, dry_run=True)
    reverify.check(conn, now=NOW, facts=dict(M2), lane="", dry_run=True)
    assert conn.total_changes == before
    assert _bytes(path) == file_before
    conn.close()


def test_every_read_only_caller_runs_on_a_mode_ro_store(path):
    ro = _read_only(path)
    try:
        report.lanes_state(ro, now=NOW)
        sweeps.check(ro, now=NOW, dry_run=True)
        got = reverify.check(ro, now=NOW, facts=dict(M2), lane="", dry_run=True)
    finally:
        ro.close()
    assert got["planned"] and not got["queued"]


def test_a_renamed_model_resolves_to_its_old_row_read_only(tmp_path):
    p = tmp_path / "d.db"
    conn = ms.connect(p)
    new_spec = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
    runs.record(conn, "runs/old", {"generated": "2026-10-01T10:00:00",
                                   "receipt": {"modality": "code", "tier": "measure"}, "environment": {},
                                   "specs": {"q3-4b": "q3-4b"},
                                   "rows": [{"case_id": "c", "candidate": "q3-4b", "passed": 1, "seconds": 1.0}]})
    old = conn.execute("SELECT id FROM candidates WHERE spec = 'q3-4b'").fetchone()["id"]
    conn.close()
    ro = _read_only(p)
    try:
        assert candidates.served(ro, new_spec, lane="code", config=MAC) == old
        assert candidates.served(ro, "never-ran", lane="code", config=MAC) is None
    finally:
        ro.close()


def test_a_queued_reverify_creates_the_row_the_lookup_did_not(tmp_path, monkeypatch):
    conftest.stand_in_machine(monkeypatch, M2)
    conn = ms.connect(tmp_path / "d.db")
    spec = reverify.served(conn)["code"]["spec"]
    assert candidates.get(conn, spec) is None
    assert reverify.served(conn)["code"]["candidate_id"] is None
    got = reverify.check(conn, now=NOW, facts=dict(M2), lane="code")
    assert got["queued"]
    row = conn.execute("SELECT candidate_id, spec FROM reverifications").fetchone()
    assert row["spec"] == spec and row["candidate_id"] == candidates.get(conn, spec)["id"]
    conn.close()
