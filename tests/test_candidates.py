"""One stored mapping between a proposal, its spec and its receipt key. #407."""
import json
import re
import sqlite3

import pytest

from harness import adopt, candidates
from harness import memory_store as ms

REPO = "ornith-ai/Ornith-1.5-35B-A3B-GGUF"
SPEC = "llamacpp:Ornith-1.5-35B-Q4_K_M"
MUSIC = "acestep/acestep-v15-turbo@steps=8"


def _schema_23(path):
    """A store as schema 23 left it: proposal_id NOT NULL, no candidate_id."""
    block = re.search(r"CREATE TABLE IF NOT EXISTS verdicts \(.*?\n\);",
                      ms._DDL, re.S).group(0)
    old = (block.replace("proposal_id INTEGER REFERENCES",
                         "proposal_id INTEGER NOT NULL REFERENCES")
           .replace("until       TEXT NOT NULL DEFAULT '',\n"
                    "    candidate_id INTEGER REFERENCES candidates(id)",
                    "until       TEXT NOT NULL DEFAULT ''"))
    conn = sqlite3.connect(path)
    conn.executescript(ms._DDL.replace(block, old).replace(
        "CREATE INDEX IF NOT EXISTS ix_cand_prop ON candidates(proposal_id);", "")
        .replace("CREATE INDEX IF NOT EXISTS ix_cand_key ON candidates(receipt_key);", ""))
    conn.execute("DROP TABLE candidates")
    conn.execute("INSERT INTO meta VALUES ('schema', '23')")
    assert "candidate_id" not in {r[1] for r in conn.execute(
        "PRAGMA table_info(verdicts)")}
    return conn


def _proposal(conn, name, lane, source="feeds"):
    pid = conn.execute(
        "INSERT INTO proposals (name, lane, first_seen, last_seen) "
        "VALUES (?, ?, 0, 0)", (name, lane)).lastrowid
    conn.execute("INSERT INTO sightings (proposal_id, source, seen_at) "
                 "VALUES (?, ?, 0)", (pid, source))
    return pid


def _verdict(conn, pid, tier, outcome, detail=""):
    return conn.execute(
        "INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) "
        "VALUES (?, ?, ?, ?, 0)", (pid, outcome, tier, detail)).lastrowid


@pytest.fixture(params=["gguf-on-disk", "gguf-absent"])
def old_store(tmp_path, monkeypatch, request):
    monkeypatch.setattr("harness.paths.home", lambda: tmp_path)
    # The GGUF's presence is a fact about the machine; pin both states.
    models = tmp_path / "gguf"
    models.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(models))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    if request.param == "gguf-on-disk":
        (models / "Ornith-1.5-35B-Q4_K_M.gguf").write_bytes(b"")
    (tmp_path / "gguf-sources.json").write_text(
        json.dumps({REPO: "Ornith-1.5-35B-Q4_K_M.gguf"}), encoding="utf-8")
    path = tmp_path / "d.db"
    conn = _schema_23(path)
    real = _proposal(conn, REPO, "code")
    _verdict(conn, real, "screen", "screened", "1 case passed")
    fake = _proposal(conn, SPEC, "code", source="adopt")
    _verdict(conn, fake, "adopt", "measured", "code: beats q3-4b")
    _verdict(conn, real, "measure", "measured", "code: already the default")
    music = _proposal(conn, MUSIC, "music", source="adopt")
    _verdict(conn, music, "adopt", "measured", "music: preferred by hand")
    conn.commit()
    conn.close()
    return path


def _latest(conn):
    return {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT p.name, v.tier, v.outcome FROM proposals p JOIN verdicts v "
        "ON v.id = (SELECT MAX(id) FROM verdicts WHERE proposal_id = p.id)")}


def test_the_migration_merges_spec_named_proposals_into_the_table(old_store):
    raw = sqlite3.connect(old_store)
    before = _latest(raw)
    outcomes = sorted(r[0] for r in raw.execute("SELECT outcome FROM verdicts"))
    raw.close()
    conn = ms.connect(old_store)
    try:
        names = {r["name"] for r in conn.execute("SELECT name FROM proposals")}
        assert names == {REPO}, names
        mine = {r[0] for r in conn.execute(
            "SELECT c.spec FROM candidates c JOIN proposals p "
            "ON p.id = c.proposal_id WHERE p.name = ?", (REPO,))}
        assert SPEC in mine, mine
        assert adopt.adopted(conn) == {
            "code": SPEC, "music": "acestep:acestep-v15-turbo,steps=8"}
        assert _latest(conn)[REPO] == before[REPO]
        assert sorted(r[0] for r in conn.execute(
            "SELECT outcome FROM verdicts")) == outcomes
        moved = conn.execute(
            "SELECT p.name FROM verdicts v JOIN proposals p "
            "ON p.id = v.proposal_id WHERE v.tier = 'adopt'").fetchall()
        assert [r[0] for r in moved] == [REPO]
    finally:
        conn.close()


def test_a_moved_verdict_never_becomes_the_proposals_latest(old_store):
    """A fake's adopt row newer than the real proposal's last verdict stays on
    the candidate alone, so the migration decides nothing."""
    raw = sqlite3.connect(old_store)
    fake = raw.execute("SELECT id FROM proposals WHERE name = ?",
                       (SPEC,)).fetchone()[0]
    _verdict(raw, fake, "adopt", "declined", "code: lost later")
    raw.commit()
    before = _latest(raw)[REPO]
    raw.close()
    conn = ms.connect(old_store)
    try:
        assert _latest(conn)[REPO] == before
        row = conn.execute(
            "SELECT proposal_id, candidate_id FROM verdicts "
            "WHERE detail = 'code: lost later'").fetchone()
        assert row["proposal_id"] is None and row["candidate_id"]
    finally:
        conn.close()


def test_the_new_store_records_a_candidate_with_no_proposal():
    """A typed default or command-line spec gets a row, not a fake proposal."""
    conn = ms.connect()
    try:
        adopt.record(conn, adopt.Verdict("music", "x", "y", True, "won"),
                     spec="acestep:acestep-v15-turbo,steps=8")
        assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
        assert adopt.adopted(conn) == {
            "music": "acestep:acestep-v15-turbo,steps=8"}
    finally:
        conn.close()


def test_a_label_that_is_no_runnable_spec_is_refused():
    conn = ms.connect()
    try:
        with pytest.raises(ValueError):
            adopt.record(conn, adopt.Verdict("image", "x", "y", True, "won"),
                         spec="mflux:")
    finally:
        conn.close()


def test_a_receipt_key_beats_the_computed_one():
    """The receipt is evidence of what ran; a later rename must not erase it."""
    conn = ms.connect()
    try:
        cid = candidates.ensure(conn, "mflux:org/pic", key="mflux/org/pic-q8")
        assert candidates.ensure(conn, "mflux:org/pic", lane="image") == cid
        assert candidates.key_for(conn, "mflux:org/pic") == "mflux/org/pic-q8"
        assert candidates.get(conn, "mflux/org/pic-q8")["spec"] == "mflux:org/pic"
    finally:
        conn.close()
