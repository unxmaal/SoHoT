"""A retried migration imports the legacy JSON files no second time. #496."""
import json

from harness import downloads, memory_store as ms, paths

VOTE = {"lane": "svg", "case": "icon-1", "left": "b", "right": "a",
        "winner": "a", "shown_first": "left"}


def _votes(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM human_votes").fetchone()[0]


def test_human_votes_import_once_and_keep_a_vote_cast_twice(tmp_path):
    f = tmp_path / "human-verdicts.json"
    f.write_text(json.dumps([VOTE, VOTE, {**VOTE, "case": "icon-2"}]), encoding="utf-8")
    conn = ms.connect(tmp_path / "s.db")
    try:
        assert ms.import_human_verdicts_json(conn, f) == 3
        assert ms.import_human_verdicts_json(conn, f) == 0
        assert _votes(conn) == 3
    finally:
        conn.close()


def test_a_judge_page_vote_does_not_stand_in_for_a_file_vote(tmp_path):
    f = tmp_path / "human-verdicts.json"
    f.write_text(json.dumps([VOTE]), encoding="utf-8")
    conn = ms.connect(tmp_path / "s.db")
    try:
        conn.execute("INSERT INTO human_votes (lane, run, case_id, left_candidate, "
                     "right_candidate, winner, shown_first, voter, at) VALUES "
                     "('svg', 'run-1', 'icon-1', 'a', 'b', 'a', 'left', 'page', 1)")
        assert ms.import_human_verdicts_json(conn, f) == 1
        assert _votes(conn) == 2
    finally:
        conn.close()


def test_memory_limits_import_once(tmp_path):
    f = tmp_path / "memory-limits.json"
    f.write_text(json.dumps({"Mac14,12/macOS-26.0/arm64": [
        {"measured_at": "2026-09-20T10:00:00", "margin_gb": 6.5}]}), encoding="utf-8")
    conn = ms.connect(tmp_path / "s.db")
    try:
        assert ms.import_memory_limits_json(conn, f) == 1
        assert ms.import_memory_limits_json(conn, f) == 0
        assert conn.execute("SELECT COUNT(*) FROM memory_limits").fetchone()[0] == 1
    finally:
        conn.close()


def test_downloads_backfill_records_a_gone_path_once(tmp_path):
    manifest = paths.home() / "gguf-sources.json"
    manifest.write_text(json.dumps({"org/gone": "gone-Q4_K_M.gguf"}), encoding="utf-8")
    conn = ms.connect(tmp_path / "s.db")
    try:
        hub, ggufs = tmp_path / "hub", tmp_path / "gguf"
        downloads.backfill(conn, hub, ggufs, manifest)
        first = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        downloads.backfill(conn, hub, ggufs, manifest)
        assert conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0] == first == 1
    finally:
        conn.close()
