"""`soh store dry-run`: migrate a copy of a store, never the store. #478."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from harness import cli, memory_store as ms
from harness import migration_check as mc
from harness import paths

GOLDEN = Path(__file__).parent / "golden"
_spec = importlib.util.spec_from_file_location("golden_build", GOLDEN / "build.py")
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def old_home(tmp_path, monkeypatch):
    """A machine's home with a schema-18 store, as LOCALHARNESS_HOME."""
    db, home = gb.load(GOLDEN / "v18", tmp_path / "machine")
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    return db, home


def test_a_dry_run_migrates_a_copy_and_reports(old_home):
    db, home = old_home
    before = _tree(home)
    got = mc.dry_run(db)
    assert got["ok"], got
    assert got["schema_from"] == 18 and got["schema_to"] == ms.SCHEMA_VERSION
    assert {c["name"] for c in got["invariants"]} == set(mc.INVARIANTS)
    assert got["rerun"] == {}
    assert got["counts_after"]["human_votes"] == len(gb.VOTES)
    assert _tree(home) == before
    assert not Path(got["copy"]).exists()


def test_the_default_is_the_store_under_the_home(old_home):
    db, _ = old_home
    got = mc.dry_run()
    assert Path(got["source"]) == db.resolve()
    assert got["schema_from"] == 18


def test_keep_leaves_the_migrated_copy_outside_the_home(old_home):
    db, home = old_home
    got = mc.dry_run(db, keep=True)
    copy = Path(got["copy"])
    assert copy.exists() and not copy.resolve().is_relative_to(home.resolve())
    conn = ms.connect(copy)
    try:
        assert mc.schema(conn) == ms.SCHEMA_VERSION
    finally:
        conn.close()


def test_the_environment_is_restored(old_home):
    db, home = old_home
    mc.dry_run(db)
    assert paths.home() == home.resolve()
    assert ms.migrating() is None


def test_a_broken_store_fails_the_dry_run(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "home"))
    db = tmp_path / "home" / "discovery.db"
    conn = ms.connect(db)
    ms.record(conn, ms.Seen(name="org/a", source="t"), at=1.0)
    ms.decide(conn, "org/a", "queued", tier=ms.INSPECT, reason="candidate")
    conn.execute("UPDATE verdicts SET reason = ''")
    conn.commit()
    conn.close()
    got = mc.dry_run(db)
    assert not got["ok"]
    assert [c["name"] for c in got["invariants"] if not c["ok"]] == ["verdict_reason"]


def test_a_missing_store_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        mc.dry_run(tmp_path / "nope.db")
    assert not (tmp_path / "nope.db").exists()


def test_the_command_prints_one_json_report(old_home, capsys):
    db, _ = old_home
    assert cli.main(["store", "dry-run", str(db), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["verb"] == "store"
    assert out["schema_from"] == 18


def test_the_command_says_what_it_did_and_fails_on_a_broken_store(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "home"))
    db = tmp_path / "home" / "discovery.db"
    conn = ms.connect(db)
    conn.execute("INSERT INTO downloads (repo, kind, path) VALUES ('x', 'zip', '')")
    conn.commit()
    conn.close()
    assert cli.main(["store", "dry-run"]) == 1
    text = capsys.readouterr().out
    assert "downloads_sane" in text and "FAIL" in text
    assert f"schema {ms.SCHEMA_VERSION} -> {ms.SCHEMA_VERSION}" in text


def test_the_report_text_names_every_check(old_home):
    db, _ = old_home
    text = mc.report_text(mc.dry_run(db))
    for name in mc.INVARIANTS:
        assert name in text
    assert "schema 18 -> " in text


def test_without_symlink_rights_the_receipts_are_copied(old_home, monkeypatch):
    db, home = old_home
    (home / "runs" / gb.RUNS[0][0] / "big.png").write_bytes(b"x")

    def refuse(self, *a, **k):
        raise OSError("symlink not permitted")
    monkeypatch.setattr(Path, "symlink_to", refuse)
    got = mc.dry_run(db, keep=True)
    runs = Path(got["copy"]).parent / "runs"
    assert got["ok"] and got["counts_after"]["runs"] == len(gb.RUNS)
    assert (runs / gb.RUNS[0][0] / "results.json").is_file()
    assert not (runs / gb.RUNS[0][0] / "big.png").exists()
