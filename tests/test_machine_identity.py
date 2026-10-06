"""One machine is one machines row, and its facts live in the store. #415.

The fingerprint held platform.platform(), which differs between two Python
builds on the same Mac, so the Studio carried two rows and the M2 Pro three.
No test here probes the real machine: every fact is passed in.
"""
import json

import pytest

from harness import machine, ramp, runs
from harness import memory_store as ms

UV_PY = "macOS-27.0.1-arm64-arm-64bit-Mach-O"
DEPLOY_PY = "macOS-27.0.1-arm64-arm-64bit"


def facts(hw="Mac17,15", os_=UV_PY, arch="arm64", **kw):
    got = {"hw_model": hw, "os": os_, "arch": arch, "memory_gb": 96.0,
           "accelerator": "unified 96GB", "runtimes": "cpu,mlx",
           "ceiling_gb": 66.0, "versions": {}}
    got.update(kw)
    got["fingerprint"] = machine.fingerprint(hw, os_, arch)
    return got


@pytest.fixture
def on(monkeypatch):
    def be(f):
        monkeypatch.setattr(ms, "_THIS_MACHINE", dict(f))
    be(facts())
    return be


# --- the identity ---------------------------------------------------------------

def test_two_interpreters_on_one_machine_share_a_fingerprint():
    assert machine.fingerprint("Mac17,15", UV_PY, "arm64") == \
        machine.fingerprint("Mac17,15", DEPLOY_PY, "arm64") == "Mac17,15/macOS/arm64"
    # An older Python spelled the same OS Darwin.
    assert machine.fingerprint("Mac17,15", "Darwin-25.0.0-arm64-arm-64bit",
                               "arm64") == "Mac17,15/macOS/arm64"


def test_different_hardware_or_os_family_is_a_different_machine():
    """Negative control: the merge must not fold rigs comparable() keeps apart."""
    assert machine.fingerprint("Mac14,12", UV_PY, "arm64") != \
        machine.fingerprint("Mac17,15", UV_PY, "arm64")
    linux = machine.fingerprint("MS-7D25", "Linux-6.8.0-x86_64-with-glibc2.39",
                                "x86_64")
    windows = machine.fingerprint("MS-7D25", "Windows-11-SP0", "x86_64")
    assert linux == "MS-7D25/Linux/x86_64" and windows == "MS-7D25/Windows/x86_64"


def test_receipts_from_two_interpreters_land_on_one_row(tmp_path, on):
    conn = ms.connect(tmp_path / "s.db")
    a = runs.machine_for(conn, {"hw_model": "Mac17,15", "os": UV_PY, "arch": "arm64"})
    b = runs.machine_for(conn, {"hw_model": "Mac17,15", "os": DEPLOY_PY,
                                "arch": "arm64"})
    c = runs.machine_for(conn, {"hw_model": "Mac14,12", "os": DEPLOY_PY,
                                "arch": "arm64"})
    assert a == b != c
    # remember_machine and a receipt agree on which row is this machine.
    assert ms.remember_machine(conn) == a
    assert runs.here(conn) == [a]
    conn.close()


def test_the_same_board_under_another_os_is_not_here(tmp_path, on):
    """hw_model stood in for identity and pooled the 4070 box's two OSes."""
    linux_os, windows_os = "Linux-6.8.0-x86_64-with-glibc2.39", "Windows-11-10.0"
    conn = ms.connect(tmp_path / "s.db")
    linux = runs.machine_for(conn, {"hw_model": "MS-7D25", "os": linux_os,
                                    "arch": "x86_64"})
    runs.machine_for(conn, {"hw_model": "MS-7D25", "os": windows_os,
                            "arch": "x86_64"})
    on(facts("MS-7D25", linux_os, "x86_64"))
    assert runs.here(conn) == [linux]
    conn.close()


# --- the merge ------------------------------------------------------------------

def _old_store(path):
    """A schema-29 store holding the duplicate rows the live one has."""
    conn = ms.connect(path)
    rows = {}
    for key, fp, hw, os_ in (
            ("studio_a", f"Mac17,15/{DEPLOY_PY}/arm64", "Mac17,15", DEPLOY_PY),
            ("studio_b", f"Mac17,15/{UV_PY}/arm64", "Mac17,15", UV_PY),
            ("m2", f"Mac14,12/{DEPLOY_PY}/arm64", "Mac14,12", DEPLOY_PY)):
        rows[key] = conn.execute(
            "INSERT INTO machines (fingerprint, hw_model, os, arch, memory_gb, "
            "runtimes, ceiling_gb, first_seen, last_seen) "
            "VALUES (?,?,?,'arm64',96,?,66,?,?)",
            (fp, hw, os_, "cpu,mlx" if key == "studio_b" else "",
             1.0 if key == "studio_a" else 2.0,
             5.0 if key == "studio_b" else 3.0)).lastrowid
    conn.execute("INSERT INTO candidates (spec, receipt_key, lane, created_at) "
                 "VALUES ('org/a', 'org/a', 'code', 0)")
    cid = conn.execute("SELECT id FROM candidates").fetchone()[0]
    for key in ("studio_a", "studio_b", "m2"):
        mid = rows[key]
        conn.execute("INSERT INTO verdicts (outcome, tier, detail, decided_at, "
                     "machine_id) VALUES ('declined', 'fetch', ?, 0, ?)",
                     (f"needs-vllm on Mac17,15/{UV_PY}/arm64: this machine has "
                      f"no runtime that can load these weights", mid))
        conn.execute("INSERT INTO runs (path, lane, machine_id, recorded_at) "
                     "VALUES (?, 'code', ?, 0)", (f"run-{key}", mid))
        conn.execute("INSERT INTO adoptions (lane, candidate_id, machine_id, how, "
                     "adopted_at) VALUES ('code', ?, ?, 'measured', 0)", (cid, mid))
        conn.execute("INSERT INTO human_votes (lane, case_id, left_candidate, "
                     "right_candidate, machine_id, at) "
                     "VALUES ('music', 'c', 'a', 'b', ?, 0)", (mid,))
    # A machine_id table this code does not name, as #411's downloads was.
    conn.execute("CREATE TABLE future_facts (id INTEGER PRIMARY KEY, "
                 "machine_id INTEGER REFERENCES machines(id))")
    for key in ("studio_a", "studio_b", "m2"):
        conn.execute("INSERT INTO future_facts (machine_id) VALUES (?)",
                     (rows[key],))
        conn.execute("INSERT INTO downloads (kind, path, machine_id) "
                     "VALUES ('hub', ?, ?)", (f"/w/{key}", rows[key]))
    # Schema 32, the one before #415's step, so that step runs.
    conn.execute("UPDATE meta SET value = '32' WHERE key = 'schema'")
    conn.commit()
    conn.close()
    return rows


FK_TABLES = ("verdicts", "runs", "adoptions", "human_votes", "downloads",
             "future_facts")


def test_the_migration_folds_duplicates_and_repoints_every_machine_id(tmp_path, on):
    path = tmp_path / "old.db"
    old = _old_store(path)
    conn = ms.connect(path)
    machines = {r["fingerprint"]: dict(r) for r in conn.execute(
        "SELECT * FROM machines")}
    assert set(machines) == {"Mac17,15/macOS/arm64", "Mac14,12/macOS/arm64"}
    studio = machines["Mac17,15/macOS/arm64"]
    assert studio["id"] == old["studio_a"]
    # The newest probe's facts survive, the oldest first_seen is kept.
    assert studio["os"] == UV_PY and studio["runtimes"] == "cpu,mlx"
    assert studio["first_seen"] == 1.0 and studio["last_seen"] == 5.0
    for t in FK_TABLES:
        got = sorted(r[0] for r in conn.execute(f"SELECT machine_id FROM {t}"))
        assert got == sorted([old["studio_a"], old["studio_a"], old["m2"]]), t
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    merges = [dict(r) for r in conn.execute("SELECT * FROM machine_merges")]
    assert [(m["from_id"], m["into_id"]) for m in merges] == \
        [(old["studio_b"], old["studio_a"])]
    assert merges[0]["from_fingerprint"] == f"Mac17,15/{UV_PY}/arm64"
    assert json.loads(merges[0]["repointed"]) == {
        **dict.fromkeys(FK_TABLES, 1), "memory_limits": 0, "jobs": 0}
    conn.close()


def test_a_receipt_with_no_os_joins_the_only_machine_with_that_board(tmp_path, on):
    """The live store held `Mac14,12/arm64`: 51 runs whose receipt named no OS."""
    conn = ms.connect(tmp_path / "s.db")

    def row(hw, os_, arch):
        return conn.execute(
            "INSERT INTO machines (fingerprint, hw_model, os, arch, first_seen, "
            "last_seen) VALUES (?,?,?,?,0,0)",
            (f"{hw}/{os_}/{arch}", hw, os_, arch)).lastrowid
    m2 = row("Mac14,12", DEPLOY_PY, "arm64")
    bare = row("Mac14,12", "", "arm64")
    linux = row("MS-7D25", "Linux-6.8", "x86_64")
    row("MS-7D25", "Windows-11", "x86_64")
    ambiguous = row("MS-7D25", "", "x86_64")
    for mid in (bare, ambiguous):
        conn.execute("INSERT INTO runs (path, machine_id, recorded_at) "
                     "VALUES (?, ?, 0)", (f"r{mid}", mid))
    ms.merge_duplicate_machines(conn)
    left = {r[0] for r in conn.execute("SELECT id FROM machines")}
    assert bare not in left and m2 in left
    # Negative control: two OSes on one board, so no guess is made.
    assert ambiguous in left and linux in left
    assert runs.machine_for(conn, {"hw_model": "Mac14,12", "arch": "arm64"}) == m2
    assert runs.machine_for(conn, {"hw_model": "MS-7D25",
                                   "arch": "x86_64"}) == ambiguous
    assert conn.execute("SELECT machine_id FROM runs WHERE path = ?",
                        (f"r{bare}",)).fetchone()[0] == m2
    conn.close()


def test_the_migration_takes_the_machine_out_of_fetch_details(tmp_path, on):
    _old_store(tmp_path / "old.db")
    conn = ms.connect(tmp_path / "old.db")
    details = {r[0] for r in conn.execute("SELECT detail FROM verdicts")}
    assert details == {"needs-vllm: this machine has no runtime that can load "
                       "these weights"}
    conn.close()


def test_the_migration_imports_memory_limits_json(tmp_path, on):
    from harness import memory, paths
    _old_store(tmp_path / "old.db")
    (paths.home() / "memory-limits.json").write_text(json.dumps({
        f"Mac17,15/{DEPLOY_PY}/arm64": [{"margin_gb": 18.0},
                                        {"margin_gb": 16.4}],
        "Mac14,12/macOS-26.5.1-arm64-arm-64bit/arm64": [{"margin_gb": 3.8}],
    }), encoding="utf-8")
    conn = ms.connect(tmp_path / "old.db")
    mid = ms.machine_row(conn)
    assert [r["margin_gb"] for r in ramp.runs(conn, mid)] == [18.0, 16.4]
    assert conn.execute("SELECT COUNT(*) FROM memory_limits").fetchone()[0] == 3
    assert memory.measured_reserve_gb(conn) == 18.0
    conn.close()


# --- versions -------------------------------------------------------------------

def test_remember_machine_records_versions_and_until_met_reads_them(tmp_path, on):
    on(facts(versions={"diffusers": "0.41.0", "llama.cpp": "10900", "mlx": ""}))
    conn = ms.connect(tmp_path / "s.db")
    mid = ms.remember_machine(conn)
    got = ms.recorded_facts(conn, mid)
    assert got["versions"] == {"diffusers": "0.41.0", "llama.cpp": "10900"}
    assert ms.until_met("version:diffusers>0.40.0", got)
    assert ms.until_met("version:llama.cpp>10869", got)
    # Negative controls: not newer, and not recorded at all.
    assert not ms.until_met("version:diffusers>0.41.0", got)
    assert not ms.until_met("version:mlx>0.1", got)
    conn.close()


@pytest.mark.parametrize("have,reopens", [("0.41.0", True), ("0.40.0", False)])
def test_a_version_wait_reopens_from_the_recorded_versions(tmp_path, on, have,
                                                           reopens):
    on(facts(versions={"diffusers": have}))
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="org/v", source="t", kind="weights",
                            lane="image", why="seeded"))
    ms.decide(conn, "org/v", "declined", tier="screen",
              detail="the installed runtime could not load it",
              until="version:diffusers>0.40.0")
    assert bool(ms.revisitable(conn)) is reopens
    conn.close()


def test_the_versions_probe_reads_every_venv_a_lane_runs_through(tmp_path,
                                                                  monkeypatch):
    from harness import serving, stages
    venv = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    venv.mkdir(parents=True)
    for d in ("diffusers-0.41.0.dist-info", "torch-2.8.0.dist-info",
              "ace_step-1.5.0.dist-info", "numpy-2.0.0.dist-info"):
        (venv / d).mkdir()
    monkeypatch.setattr(stages, "tool_versions", lambda: {"mflux": "0.19.1",
                                                          "mlx": "0.32.2"})
    monkeypatch.setattr(machine, "_imported_versions",
                        lambda: {"mlx": "0.31.0", "mlx-lm": "0.32.0"})
    monkeypatch.setattr(machine, "_other_venvs", lambda: [tmp_path / "venv",
                                                          tmp_path / "absent"])
    monkeypatch.setattr(machine, "_uv_with_pins", lambda: {"mlx-audio": "0.5.3"})
    monkeypatch.setattr(machine, "_mflux_cli", lambda: pytest.fail("not needed"))
    monkeypatch.setattr(serving, "llamacpp_build", lambda: "10869")
    got = machine.versions.__wrapped__()
    assert got["mlx"] == "0.32.2", "mflux's own venv wins for what it carries"
    assert got["mlx-lm"] == "0.32.0"
    assert got["diffusers"] == "0.41.0" and got["torch"] == "2.8.0"
    assert got["ace-step"] == "1.5.0" and got["mlx-audio"] == "0.5.3"
    assert got["llama.cpp"] == "10869"
    assert "numpy" not in got
