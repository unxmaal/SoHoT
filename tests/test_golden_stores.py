"""Each golden store, at its historical schema, migrates to head and holds. #478."""
import importlib.util
import json
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from harness import memory_store as ms
from harness import migration_check as mc
from harness import paths, privacy

GOLDEN = Path(__file__).parent / "golden"
_spec = importlib.util.spec_from_file_location("golden_build", GOLDEN / "build.py")
gb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gb)
ERAS = [v for v, _ in gb.ERAS]

#: The M2 Pro, under the Python whose platform string split it in two.
THIS = {"hw_model": "Mac14,12", "os": "macOS-26.0-arm64-arm-64bit-Mach-O",
        "arch": "arm64", "memory_gb": 32.0, "accelerator": "metal 32GB",
        "runtimes": "llamacpp,mlx", "ceiling_gb": 23.0, "versions": {},
        "fingerprint": "Mac14,12/macOS/arm64"}

STATES = {
    "org-a/coder-7b-GGUF": "measured", "org-b/huge-70b": "declined",
    "org-c/old-repo": "declined", "org-d/lora-x": "ignored",
    "org-e/vllm-only": "declined", "org-g/gguf-llama": "declined",
    "org-h/tts-model": "declined", "org-i/queued-only": "queued",
    "org-j/never-judged": "", "org-k/harness-broke": "queued",
    "org-l/svg-thing": "measured", "org-m/image-gen": "screened",
}


def open_golden(version, tmp_path, monkeypatch):
    db, home = gb.load(GOLDEN / f"v{version}", tmp_path)
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    monkeypatch.setattr(ms, "_THIS_MACHINE", dict(THIS))
    return db, home


@pytest.fixture(params=ERAS, ids=[f"v{v}" for v in ERAS])
def migrated(request, tmp_path, monkeypatch):
    db, home = open_golden(request.param, tmp_path, monkeypatch)
    start = time.monotonic()
    conn = ms.connect(db)
    took = time.monotonic() - start
    yield request.param, conn, db, took
    conn.close()


def test_every_era_has_a_committed_golden():
    have = sorted(int(p.name[1:]) for p in GOLDEN.glob("v*")
                  if (p / "discovery.sql").exists())
    assert have == ERAS


@pytest.mark.parametrize("version", ERAS)
def test_a_golden_is_at_its_schema(version, tmp_path, monkeypatch):
    db, _ = open_golden(version, tmp_path, monkeypatch)
    raw = sqlite3.connect(db)
    try:
        assert raw.execute("SELECT value FROM meta WHERE key = 'schema'"
                           ).fetchone()[0] == str(version)
    finally:
        raw.close()


def test_migrates_in_seconds(migrated):
    _, _, _, took = migrated
    assert took < 20


def test_holds_every_invariant(migrated):
    _, conn, _, _ = migrated
    assert [c for c in mc.invariants(conn) if not c.ok] == []


@pytest.mark.parametrize("version,step,caught", [
    (24, "backfill_reasons", "verdict_reason"),
    (24, "_backfill_state", "proposal_state"),
    (24, "merge_duplicate_machines", "machines_unique"),
    (29, "split_result_artifacts", "results_split"),
])
def test_a_migration_missing_a_step_is_caught(version, step, caught, tmp_path,
                                              monkeypatch):
    """Negative control: each invariant fails when the step it guards does not run."""
    db, _ = open_golden(version, tmp_path, monkeypatch)
    monkeypatch.setattr(ms, step, lambda *a, **k: {})
    conn = ms.connect(db)
    try:
        assert caught in {c.name for c in mc.invariants(conn) if not c.ok}
    finally:
        conn.close()


def test_every_proposal_lands_in_the_same_state(migrated):
    v, conn, _, _ = migrated
    got = {r["name"]: r["state"] for r in conn.execute(
        "SELECT name, state FROM proposals")}
    want = dict(STATES)
    # Before 16 its two screen verdicts had no evidence, and 16 retracted them.
    want["org-f/screen-broke"] = "queued" if v < 16 else "broken"
    assert got == want


def test_legacy_json_is_imported_exactly_once(migrated):
    v, conn, _, _ = migrated
    votes = conn.execute("SELECT COUNT(*) FROM human_votes WHERE run = ''").fetchone()[0]
    assert votes == len(gb.VOTES)
    assert conn.execute("SELECT COUNT(*) FROM memory_limits").fetchone()[0] == 1
    assert [r[0] for r in conn.execute("SELECT id FROM jobs ORDER BY id")] == [1, 2]
    read = {r["name"]: r["last_read_at"] for r in conn.execute(
        "SELECT name, last_read_at FROM sources")}
    assert {k: read.get(k) for k in gb.FETCHED} == gb.FETCHED
    assert conn.execute("SELECT lane FROM proposals WHERE name = "
                        "'org-i/queued-only'").fetchone()[0] == "code"


def test_migrating_again_changes_nothing(migrated):
    v, conn, db, _ = migrated
    before = list(conn.iterdump())
    conn.close()
    again = ms.connect(db)
    try:
        assert list(again.iterdump()) == before
    finally:
        again.close()


def test_rerunning_every_step_imports_nothing_twice(migrated):
    v, conn, _, _ = migrated
    assert mc.rerun(conn, v) == {}


def test_runs_and_results_in_the_head_shape(migrated):
    v, conn, _, _ = migrated
    runs = {r["path"]: r["lane"] for r in conn.execute("SELECT path, lane FROM runs")}
    assert runs == {name: lane for name, lane, *_ in gb.RUNS}
    rows = conn.execute("SELECT r.lane, x.candidate, x.case_id, x.output, "
                        "x.artifact_path FROM results x JOIN runs r ON "
                        "r.id = x.run_id").fetchall()
    assert len(rows) == sum(len(r[-1]) for r in gb.RUNS)
    for r in rows:
        if r["lane"] == "code":
            assert r["artifact_path"] is None
        else:
            assert r["output"] is None
            assert r["artifact_path"] is None or \
                r["artifact_path"].endswith((".png", ".wav"))
    assert sum(1 for r in rows if r["output"] == gb.CODE) == 4
    assert sum(1 for r in rows if r["artifact_path"]) == 6
    assert conn.execute("SELECT COUNT(*) FROM results WHERE candidate_id "
                        "IS NULL").fetchone()[0] == 0


def test_adoptions_resolve_to_their_candidates(migrated):
    v, conn, _, _ = migrated
    got = {(r["lane"], r["name"], r["how"]): r["spec"] for r in conn.execute(
        "SELECT a.lane, p.name, c.spec, a.how FROM adoptions a "
        "JOIN candidates c ON c.id = a.candidate_id "
        "JOIN proposals p ON p.id = c.proposal_id")}
    assert set(got) == {("code", "org-a/coder-7b-GGUF", "measured"),
                        ("svg", "org-l/svg-thing", "by-hand")}
    # The code adoption's run receipt recorded its spec; the golden has no weights. #506.
    assert got[("code", "org-a/coder-7b-GGUF", "measured")] == "llamacpp:coder-7b-Q4_K_M"
    if v >= 24:
        assert got[("svg", "org-l/svg-thing", "by-hand")] == "mlx:org-l/svg-thing"
    else:
        # No run backs the by-hand svg verdict: its spec is a recorded guess.
        row = conn.execute("SELECT value FROM meta WHERE key = "
                           "'candidate_guesses'").fetchone()
        guessed = {g["proposal"] for g in json.loads(row[0])}
        assert "org-l/svg-thing" in guessed
        assert "org-a/coder-7b-GGUF" not in guessed


def test_one_row_per_machine(migrated):
    v, conn, _, _ = migrated
    got = {r[0] for r in conn.execute("SELECT fingerprint FROM machines")}
    want = {"Mac14,12/macOS/arm64", "Mac17,15/macOS/arm64"}
    if v >= 12:
        want |= {"B650M/Linux/x86_64", "B650M/Windows/AMD64"}
    assert got == want


def test_downloads_are_one_row_per_path(migrated):
    v, conn, _, _ = migrated
    got = conn.execute("SELECT repo, kind, path, removed_at IS NOT NULL AS gone "
                       "FROM downloads ORDER BY repo, path").fetchall()
    paths_ = [r["path"] for r in got]
    assert len(paths_) == len(set(paths_))
    want = {"org-a/coder-7b-GGUF": "hub", "org-h/tts-model": "hub",
            "org-g/gguf-llama": "gguf"}
    if v >= 24:
        # `lh disk` and its disk_removals table arrived between 18 and 24.
        want["org-f/screen-broke"] = "hub"
    assert {r["repo"]: r["kind"] for r in got} == want
    if v < 31:
        # The backfill looked, and the golden has no weights on disk.
        assert all(r["gone"] for r in got)


def test_goldens_carry_no_home_paths_hosts_or_names():
    extra = privacy.name_pattern(Path(__file__).parents[1])
    found = []
    for f in sorted(GOLDEN.rglob("*")):
        if f.is_file() and f.suffix in (".sql", ".json", ".py"):
            found += privacy.scan(f.read_text(encoding="utf-8"), str(f), extra)
    assert found == []


def test_the_privacy_scan_sees_a_home_path():
    """Negative control: the scan above would see what it guards against."""
    assert privacy.scan("'/Users/someone/localharness/runs'", "x")  # privacy-ok


def _history_has(sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                          cwd=GOLDEN, capture_output=True).returncode == 0


@pytest.mark.parametrize("version,sha", gb.ERAS, ids=[f"v{v}" for v in ERAS])
def test_the_build_reproduces_the_committed_golden(version, sha, tmp_path):
    if not _history_has(sha):
        pytest.skip(f"{sha} not in this clone (shallow checkout)")
    built = gb.build(version, sha, tmp_path)
    committed = GOLDEN / f"v{version}"
    files = sorted(p.relative_to(built) for p in built.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(committed)
                           for p in committed.rglob("*") if p.is_file())
    for f in files:
        assert (built / f).read_bytes() == (committed / f).read_bytes(), f
