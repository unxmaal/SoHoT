"""The invariants a migrated store must hold, each seen to fail on a broken store. #478."""
import sqlite3

import pytest

from harness import memory_store as ms
from harness import migration_check as mc


@pytest.fixture
def head(tmp_path):
    conn = ms.connect(tmp_path / "head.db")
    for name in ("org/a", "org/b"):
        ms.record(conn, ms.Seen(name=name, source="test"), at=1.0)
    ms.decide(conn, "org/a", "queued", tier=ms.INSPECT, detail="fits: 1 GiB",
              reason="candidate")
    ms.decide(conn, "org/b", "declined", tier=ms.INSPECT,
              detail="too-big: 90 GiB", reason="machine")
    yield conn
    conn.close()


def failing(conn) -> set[str]:
    return {c.name for c in mc.invariants(conn) if not c.ok}


def test_a_fresh_head_store_holds_every_invariant(head):
    assert failing(head) == set()
    assert {c.name for c in mc.invariants(head)} == set(mc.INVARIANTS)


def test_a_verdict_with_no_reason_fails(head):
    head.execute("UPDATE verdicts SET reason = '' WHERE id = 1")
    assert failing(head) == {"verdict_reason"}


def test_a_state_its_verdict_does_not_hold_fails(head):
    head.execute("UPDATE proposals SET state = 'measured' WHERE name = 'org/a'")
    assert failing(head) == {"proposal_state"}


def test_a_decided_proposal_with_no_state_fails(head):
    head.execute("UPDATE proposals SET state = '', state_verdict_id = NULL "
                 "WHERE name = 'org/b'")
    assert failing(head) == {"proposal_state"}


def test_a_state_held_by_another_proposals_verdict_fails(head):
    head.execute("UPDATE proposals SET state_verdict_id = 2 WHERE name = 'org/a'")
    head.execute("UPDATE proposals SET state = 'declined' WHERE name = 'org/a'")
    assert failing(head) == {"proposal_state"}


def test_an_adoption_of_no_candidate_fails(head):
    head.execute("PRAGMA foreign_keys = OFF")
    head.execute("INSERT INTO adoptions (lane, candidate_id, how, adopted_at) "
                 "VALUES ('code', 99, 'measured', 1)")
    assert failing(head) == {"adoptions_resolve", "foreign_keys"}


def test_an_adoption_with_no_lane_or_unknown_how_fails(head):
    head.execute("INSERT INTO candidates (spec, receipt_key, created_at) "
                 "VALUES ('local-mid', 'local-mid', 1)")
    head.execute("INSERT INTO adoptions (lane, candidate_id, how, adopted_at) "
                 "VALUES ('', 1, 'guessed', 1)")
    assert failing(head) == {"adoptions_resolve"}


def test_two_rows_for_one_machine_fail(head):
    for os_ in ("macOS-26.0-arm64-arm-64bit", "macOS-26.0-arm64-arm-64bit-Mach-O"):
        head.execute("INSERT INTO machines (fingerprint, hw_model, os, arch, "
                     "first_seen, last_seen) VALUES (?,?,?,?,1,1)",
                     (f"Mac14,12/{os_}/arm64", "Mac14,12", os_, "arm64"))
    assert failing(head) == {"machines_unique"}


def test_a_download_with_no_path_or_kind_fails(head):
    head.execute("INSERT INTO downloads (repo, kind, path, origin) "
                 "VALUES ('org/a', 'tarball', '', 'fetch')")
    assert failing(head) == {"downloads_sane"}


def test_a_removed_download_that_says_complete_fails(head):
    head.execute("INSERT INTO downloads (repo, kind, path, origin, complete, "
                 "removed_at) VALUES ('org/a', 'hub', '/HF/x', 'fetch', 1, 5)")
    assert failing(head) == {"downloads_sane"}


def test_a_results_table_still_carrying_artifact_fails(head):
    head.execute("ALTER TABLE results ADD COLUMN artifact TEXT")
    assert failing(head) == {"results_split"}


def test_a_schema_behind_head_fails(head):
    head.execute("UPDATE meta SET value = '41' WHERE key = 'schema'")
    assert failing(head) == {"schema"}


def test_a_dangling_foreign_key_fails(head):
    head.execute("PRAGMA foreign_keys = OFF")
    head.execute("INSERT INTO sightings (proposal_id, source, seen_at) "
                 "VALUES (99, 'x', 1)")
    assert failing(head) == {"foreign_keys"}


def test_integrity_check_is_read(head, monkeypatch):
    monkeypatch.setattr(mc, "_integrity", lambda conn: ["row 3 missing from index"])
    assert failing(head) == {"integrity"}


def test_a_rerun_that_imports_again_is_reported(head, monkeypatch):
    """Negative control for the rerun probe: a step that is not idempotent shows."""
    real = ms._migrate

    def importing(conn):
        conn.execute("INSERT INTO extractions (name, source, reason, at) "
                     "VALUES ('n', 's', 'r', 1)")
        real(conn)
    monkeypatch.setattr(ms, "_migrate", importing)
    assert mc.rerun(head, 41) == {"extractions": (0, 1)}
    assert mc.schema(head) == ms.SCHEMA_VERSION


def test_rerun_restores_nothing_on_a_head_store(head):
    assert mc.rerun(head, ms.SCHEMA_VERSION) == {}


def test_counts_cover_every_table(head):
    got = mc.counts(head)
    assert got["proposals"] == 2 and got["verdicts"] == 2
    assert "meta" not in got


def test_invariants_never_write(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    conn.close()
    before = (tmp_path / "s.db").read_bytes()
    ro = sqlite3.connect(f"file:{tmp_path / 's.db'}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    try:
        assert all(c.ok for c in mc.invariants(ro))
    finally:
        ro.close()
    assert (tmp_path / "s.db").read_bytes() == before
