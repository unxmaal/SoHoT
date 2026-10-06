"""An adoption is a row: which lane, which candidate, where, and how. #412."""
import inspect
import re

import pytest

from harness import adopt, candidates, disk, winners
from harness import memory_store as ms

M2 = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
      "os": "macOS-26", "arch": "arm64", "memory_gb": 32.0,
      "accelerator": "unified 32GB", "runtimes": "cpu,mlx", "ceiling_gb": 22.0}
STUDIO = {**M2, "fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15",
          "os": "macOS-27", "memory_gb": 96.0}
#: The M2 under another Python build: another os string, the same fingerprint.
M2_AGAIN = {**M2, "os": "macOS-26-Mach-O"}


@pytest.fixture
def on(monkeypatch):
    """Pin which machine the code believes it runs on."""
    def be(facts):
        monkeypatch.setattr(ms, "this_machine", lambda: dict(facts))
    be(M2)
    return be


@pytest.fixture
def conn(tmp_path, on):
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


def _adopt(conn, lane, spec, how=adopt.MEASURED, incumbent="old"):
    return adopt.record(conn, adopt.Verdict(lane, incumbent, spec, True,
                                            "won", how))


def test_the_readers_never_parse_detail():
    """The lane was `detail.split(":")[0]`. Nothing that reads one may."""
    for fn in (adopt.current, adopt.adopted, adopt.lane_defaults,
               adopt.default_for, adopt.everywhere):
        src = inspect.getsource(fn)
        assert "detail" not in src, fn.__name__
        assert not re.search(r"split\(\s*['\"]:", src), fn.__name__


def test_the_lane_is_the_rows_not_the_detail_prefix(conn):
    vid = _adopt(conn, "tts", "org/new")
    conn.execute("UPDATE verdicts SET detail = 'svg: reworded' WHERE id = ?",
                 (vid,))
    assert adopt.adopted(conn) == {"tts": "org/new"}


def test_an_adoption_is_a_row_naming_lane_candidate_run_and_machine(conn):
    vid = _adopt(conn, "tts", "org/new", incumbent="org/old")
    row = dict(conn.execute("SELECT * FROM adoptions").fetchone())
    assert row["lane"] == "tts" and row["verdict_id"] == vid
    assert row["candidate_id"] == candidates.get(conn, "org/new")["id"]
    inc = conn.execute("SELECT spec FROM candidates WHERE id = ?",
                       (row["incumbent_id"],)).fetchone()
    assert inc and inc["spec"].endswith("org/old")
    assert row["how"] == adopt.MEASURED
    assert row["machine_id"] == ms.remember_machine(conn, M2)


def test_a_loss_writes_no_adoption(conn):
    adopt.record(conn, adopt.Verdict("tts", "old", "org/new", False, "lost"))
    assert conn.execute("SELECT COUNT(*) FROM adoptions").fetchone()[0] == 0
    assert adopt.adopted(conn) == {}


def test_a_newer_adoption_replaces_the_older_for_the_lane(conn):
    _adopt(conn, "tts", "org/first")
    _adopt(conn, "tts", "org/second")
    _adopt(conn, "stt", "org/ear")
    assert adopt.adopted(conn) == {"tts": "org/second", "stt": "org/ear"}


def test_a_lane_with_no_adoption_serves_its_typed_default(conn):
    _adopt(conn, "tts", "org/new")
    got = adopt.lane_defaults(conn, typed={"tts": "T", "stt": "S"})
    assert got == {"tts": "org/new", "stt": "S"}
    assert adopt.default_for("stt", "S", conn) == "S"


@pytest.mark.parametrize("spec", ["claude-code:opus", "cloud-sonnet"])
def test_a_reference_model_is_never_a_lane_default(conn, spec):
    """#374: references exist to measure against, not to serve."""
    _adopt(conn, "code", "org/local")
    _adopt(conn, "code", spec)
    assert adopt.adopted(conn) == {"code": "org/local"}
    cid = candidates.ensure(conn, spec, lane="code")
    conn.execute("INSERT INTO adoptions (lane, candidate_id, how, adopted_at) "
                 "VALUES ('code', ?, 'measured', 9e12)", (cid,))
    assert adopt.adopted(conn) == {"code": "org/local"}


def test_a_measured_adoption_serves_only_the_machine_that_measured_it(
        conn, on):
    on(STUDIO)
    _adopt(conn, "code", "org/big")
    assert adopt.adopted(conn) == {"code": "org/big"}
    on(M2)
    assert adopt.adopted(conn) == {}
    assert adopt.default_for("code", "q3-4b", conn) == "q3-4b"


def test_the_same_machine_under_another_python_is_one_row(conn, on):
    """#415: one machine is one row, so no hw_model stand-in is needed."""
    _adopt(conn, "code", "org/mine")
    on(M2_AGAIN)
    ms.remember_machine(conn)
    assert conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0] == 1
    assert adopt.adopted(conn) == {"code": "org/mine"}


def test_a_by_hand_adoption_serves_every_machine(conn, on):
    """A person's preference for a config is not a fact about hardware."""
    _adopt(conn, "music", "org/steps8", how=adopt.BY_HAND)
    on(STUDIO)
    assert adopt.adopted(conn) == {"music": "org/steps8"}


def test_a_local_measurement_beats_an_older_remote_preference(conn, on):
    _adopt(conn, "music", "org/by-hand", how=adopt.BY_HAND)
    on(STUDIO)
    _adopt(conn, "music", "org/measured")
    assert adopt.adopted(conn) == {"music": "org/measured"}
    on(M2)
    assert adopt.adopted(conn) == {"music": "org/by-hand"}


def test_decide_by_hand_records_by_hand(monkeypatch):
    from harness import human
    monkeypatch.setattr(human, "lane_verdict", lambda lane, pairs: ("b", "2-0"))
    assert adopt.decide_by_hand("music", "a", "b", []).how == adopt.BY_HAND


def test_disk_keeps_every_machines_adoption(conn, on):
    on(STUDIO)
    _adopt(conn, "code", "org/studio-only")
    on(M2)
    assert adopt.everywhere(conn) == {"code": {"org/studio-only"}}
    keep = disk.keepers(conn, gateway_files=[], typed={})
    assert "org/studio-only" in keep.repos


def test_winners_compare_against_what_the_lane_serves(conn, monkeypatch):
    monkeypatch.setattr(winners, "typed", lambda: {"tts": "org/typed"})
    _adopt(conn, "tts", "org/new")
    assert winners.served_ids(conn)["tts"] == candidates.get(conn, "org/new")["id"]
    assert [r["typed"] for r in winners.disagreements(conn)] == ["org/new"]


def test_the_migration_backfills_adopt_verdicts(tmp_path, on):
    path = tmp_path / "old.db"
    c = ms.connect(path)
    m2 = ms.remember_machine(c, M2)
    studio = ms.remember_machine(c, STUDIO)
    cid = {s: candidates.ensure(c, s, lane="x") for s in
           ("org/a", "org/b", "org/c", "claude-code:opus")}

    def verdict(spec, detail, outcome="measured", machine=m2, at=1.0):
        c.execute("INSERT INTO verdicts (outcome, tier, detail, decided_at, "
                  "machine_id, candidate_id) VALUES (?, 'adopt', ?, ?, ?, ?)",
                  (outcome, detail, at, machine, cid[spec]))
    verdict("org/a", "code: beats q3-4b", machine=studio, at=1)
    verdict("org/b", "music: preferred by hand: won 2 of 4", at=2)
    verdict("org/c", "code: does not beat the incumbent", "declined", at=3)
    verdict("claude-code:opus", "code: beats everything", at=4)
    c.execute("DELETE FROM adoptions")
    c.execute("UPDATE meta SET value = '27' WHERE key = 'schema'")
    c.commit()
    c.close()
    c = ms.connect(path)
    rows = {r["lane"]: dict(r) for r in c.execute("SELECT * FROM adoptions")}
    assert set(rows) == {"code", "music"}
    assert rows["code"]["how"] == adopt.MEASURED
    assert rows["code"]["machine_id"] == studio
    assert rows["music"]["how"] == adopt.BY_HAND
    assert adopt.adopted(c) == {"music": "org/b"}
    on(STUDIO)
    assert adopt.adopted(c) == {"code": "org/a", "music": "org/b"}
    c.close()
