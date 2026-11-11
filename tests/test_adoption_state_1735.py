"""What a lane serves is a declared chain of named moves with one writer and one resolver. #1735."""
import json
import re
from pathlib import Path

import pytest

from harness import adopt, adoption_state as st, candidates, lane_feed, publish, winners
from harness import memory_store as ms
from tests import conftest

M2 = {"fingerprint": "Mac14,12/macOS/arm64", "hw_model": "Mac14,12",
      "os": "macOS-26", "arch": "arm64", "memory_gb": 32.0,
      "accelerator": "unified 32GB", "runtimes": "cpu,mlx", "ceiling_gb": 22.0}
STUDIO = {**M2, "fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15",
          "os": "macOS-27", "memory_gb": 96.0, "ceiling_gb": 66.0}
GIB = 1024 ** 3
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    conftest.stand_in_machine(monkeypatch, STUDIO)
    c = ms.connect()
    ms.remember_machine(c)
    c.commit()
    yield c
    c.close()


def _cid(conn, spec, lane="code", size_gib=None):
    if size_gib is None:
        return candidates.ensure(conn, spec, lane=lane)
    conn.execute("INSERT INTO proposals (name, lane, first_seen, last_seen) VALUES (?, ?, 1.0, 1.0)", (spec, lane))
    cid = candidates.ensure(conn, spec, proposal=spec, lane=lane)
    conn.execute("UPDATE proposals SET size_bytes = ? WHERE name = ?", (int(size_gib * GIB), spec))
    conn.commit()
    return cid


def _adopt(conn, lane, spec, how=adopt.MEASURED, machine=None, **kw):
    mid = ms.machine_row(conn) if machine is None else machine
    return st.move(conn, lane, st.ADOPT, _cid(conn, spec, lane, kw.pop("size_gib", None)), how=how,
                   machine_id=mid, **kw)


def test_a_lane_never_adopted_is_named_configured_and_serves_its_default(conn):
    got = st.serving(conn, "code", typed={"code": "typed-x"})
    assert (got.state, got.spec, got.row) == (st.CONFIGURED, "typed-x", None)
    assert "configured default, never adopted" in got.says()
    assert st.serving(conn, "code", typed={}).state == st.NONE


def test_withdrawing_an_adoption_returns_the_lane_to_its_configured_default(conn, monkeypatch):
    from harness import screen
    monkeypatch.setattr(winners, "typed", lambda: {"code": "typed-x"})
    typed_id = candidates.ensure(conn, screen.candidate_for("code", "typed-x") or "typed-x", lane="code")
    _adopt(conn, "code", "org/a")
    assert winners.served_ids(conn) == {"code": candidates.get(conn, "org/a")["id"]}
    assert adopt.lane_defaults(conn, typed={"code": "typed-x"}) == {"code": "org/a"}
    aid = st.withdraw(conn, "code", "serves garbage since the llama.cpp bump")
    got = st.serving(conn, "code", typed={"code": "typed-x"})
    assert (got.state, got.spec, got.row["id"]) == (st.WITHDRAWN, "typed-x", aid)
    assert "serves garbage" in got.says()
    assert adopt.current(conn) == {}
    assert adopt.lane_defaults(conn, typed={"code": "typed-x"}) == {"code": "typed-x"}
    assert winners.served_ids(conn) == {"code": typed_id}
    _adopt(conn, "code", "org/b")
    assert st.serving(conn, "code", typed={}).spec == "org/b"


def test_a_withdrawal_with_nothing_adopted_or_no_reason_is_refused(conn):
    with pytest.raises(st.IllegalMove, match="no adoption serving"):
        st.withdraw(conn, "code", "why not")
    _adopt(conn, "code", "org/a")
    with pytest.raises(st.IllegalMove, match="says why"):
        st.withdraw(conn, "code", "  ")
    st.withdraw(conn, "code", "bad")
    with pytest.raises(st.IllegalMove, match="withdrawn"):
        st.withdraw(conn, "code", "again")
    assert len(st.history(conn)) == 2


def test_a_withdrawal_names_what_the_lane_serves(conn):
    _adopt(conn, "code", "org/a")
    other = _cid(conn, "org/other")
    with pytest.raises(st.IllegalMove, match="serves org/a"):
        st.move(conn, "code", st.WITHDRAW, other, how=adopt.BY_HAND, machine_id=ms.machine_row(conn), why="x")


def test_every_move_outside_the_table_is_refused():
    for state in st.STATES:
        for kind in st.KINDS:
            assert ((state, kind) in st.MOVES) == (kind == st.ADOPT or state == st.ADOPTED)
    assert set(st.MOVES.values()) <= set(st.STATES)


def test_an_unknown_move_is_refused(conn):
    with pytest.raises(st.IllegalMove, match="no adoption move"):
        st.move(conn, "code", "rollback", _cid(conn, "org/a"), how=adopt.MEASURED, machine_id=None)


def test_a_second_writer_leaving_the_same_head_loses(conn):
    head = _adopt(conn, "code", "org/a")
    first = _adopt(conn, "code", "org/b", head=head)
    with pytest.raises(st.Lost, match=f"adoption {first} moved the lane"):
        _adopt(conn, "code", "org/c", head=head)
    assert [r["spec"] for r in st.history(conn)] == ["org/a", "org/b"]


def test_the_store_refuses_a_racer_that_read_the_head_before_the_winner_wrote(conn, monkeypatch):
    head = _adopt(conn, "code", "org/a")
    stale = st.chains(conn, "code")
    _adopt(conn, "code", "org/b")
    monkeypatch.setattr(st, "chains", lambda c, lane=None: stale)
    with pytest.raises(st.Lost, match="another writer left adoption"):
        _adopt(conn, "code", "org/c")
    monkeypatch.undo()
    assert [r["spec"] for r in st.history(conn)] == ["org/a", "org/b"]
    assert [r["leaves"] for r in st.history(conn)] == [0, head]


def test_racing_writers_on_two_connections_leave_one_chain(conn, tmp_path):
    _adopt(conn, "code", "org/a")
    other = ms.connect()
    try:
        head_a = st.chains(conn, "code")["code"][-1]["id"]
        head_b = st.chains(other, "code")["code"][-1]["id"]
        _adopt(conn, "code", "org/b", head=head_a)
        with pytest.raises(st.Lost):
            st.move(other, "code", st.ADOPT, _cid(other, "org/c"), how=adopt.MEASURED,
                    machine_id=ms.machine_row(other), head=head_b)
    finally:
        other.close()
    assert [r["spec"] for r in st.history(conn)] == ["org/a", "org/b"]


def test_the_chain_orders_moves_not_the_clock(conn):
    _adopt(conn, "code", "org/a")
    later = _adopt(conn, "code", "org/b")
    conn.execute("UPDATE adoptions SET adopted_at = 0 WHERE id = ?", (later,))
    conn.commit()
    assert st.serving(conn, "code", typed={}).spec == "org/b"
    conn.execute("UPDATE adoptions SET adopted_at = 5")
    conn.commit()
    assert st.serving(conn, "code", typed={}).spec == "org/b"


def test_a_fit_that_changes_with_no_row_written_is_named_on_the_read(conn):
    _adopt(conn, "image", "org/small", how=adopt.MEASURED)
    _adopt(conn, "image", "org/big", how=adopt.BY_HAND, size_gib=40)
    assert st.serving(conn, "image", typed={}).spec == "org/big"
    rows = len(st.history(conn))
    conn.execute("UPDATE machines SET ceiling_gb = 20")
    conn.commit()
    got = st.serving(conn, "image", typed={})
    assert (got.state, got.spec, got.refused["spec"]) == (st.ADOPTED, "org/small", "org/big")
    assert "refused here" in got.says() and "over the 20.0 GiB ceiling" in got.says()
    assert len(st.history(conn)) == rows


def test_a_reference_model_is_refused_by_the_writer(conn):
    with pytest.raises(st.IllegalMove, match="reference model"):
        _adopt(conn, "code", "claude-code:opus")
    assert st.history(conn) == []


def test_a_verdict_recorded_twice_writes_one_row(conn):
    v = ms.decide(conn, "", "measured", tier="adopt", detail="code: won", candidate_id=_cid(conn, "org/a"))
    one = _adopt(conn, "code", "org/a", verdict_id=v)
    assert _adopt(conn, "code", "org/a", verdict_id=v) == one
    assert len(st.history(conn)) == 1


def test_every_reader_agrees_with_the_resolver_on_scope(conn):
    here = ms.machine_row(conn)
    m2 = ms.remember_machine(conn, M2)
    conn.commit()
    _adopt(conn, "video", "org/v1", machine=here)
    _adopt(conn, "video", "org/m2", machine=m2)
    _adopt(conn, "video", "org/all", how=adopt.BY_HAND, all_machines=True)
    st.withdraw(conn, "video", "flicker", machine=m2)
    want = {mid: [r["spec"] for r in st.history(conn, mid)] for mid in (here, m2)}
    assert want == {here: ["org/v1", "org/all"], m2: ["org/m2", "org/all", "org/all"]}
    for mid in (here, m2):
        assert [a["candidate"] for a in publish._adoptions(conn, mid)] == want[mid]
        doc = lane_feed.lane_feed(conn, "video", machine_id=mid)
        assert [e["candidate"] for e in doc["events"] if e["kind"] == "adoption"] == want[mid]
    assert st.serving(conn, "video", here, typed={}).spec == "org/all"
    assert st.serving(conn, "video", m2, typed={"video": "typed-v"}).state == st.WITHDRAWN
    assert winners.served_ids(conn)["video"] == candidates.get(conn, "org/all")["id"]
    assert adopt.everywhere(conn) == {"video": {"org/all"}}


def test_everywhere_unions_what_each_machine_serves(conn):
    m2 = ms.remember_machine(conn, M2)
    conn.commit()
    _adopt(conn, "code", "org/here")
    _adopt(conn, "code", "org/m2", machine=m2)
    assert adopt.everywhere(conn) == {"code": {"org/here", "org/m2"}}


def test_judge_says_the_adoption_its_verdict_made_not_the_lanes_newest(conn, capsys):
    from harness.commands import judge
    adopt.record(conn, adopt.Verdict("music", "old", "org/first", True, "won", adopt.BY_HAND, votes=12))
    mid = adopt.record(conn, adopt.Verdict("music", "org/first", "org/mid", True, "won", adopt.BY_HAND, votes=12))
    adopt.record(conn, adopt.Verdict("music", "org/mid", "org/last", True, "won", adopt.BY_HAND, votes=12))
    capsys.readouterr()
    judge._say_adopted(conn, "music", adopt.Verdict("music", "org/first", "org/mid", True, "won", adopt.BY_HAND), mid)
    said = capsys.readouterr()
    assert "adopted org/mid for music" in said.out + said.err


def test_a_row_off_its_lanes_chain_fails_the_migration_check(conn):
    from harness import migration_check
    first = _adopt(conn, "code", "org/a")
    _adopt(conn, "code", "org/b")
    assert migration_check._adoptions(conn) == []
    conn.execute("DELETE FROM adoptions WHERE id = ?", (first,))
    conn.commit()
    assert any("off the code chain" in b for b in migration_check._adoptions(conn))


def test_lane_defaults_keeps_an_adopted_lane_the_config_does_not_name(conn):
    _adopt(conn, "music", "org/m")
    st.withdraw(conn, "music", "x")
    _adopt(conn, "video", "org/v")
    assert adopt.lane_defaults(conn, typed={"tts": "T"}) == {"tts": "T", "video": "org/v"}


def test_record_writes_the_run_and_the_verdicts_reason_on_its_move(conn):
    conn.execute("INSERT INTO runs (path, lane, tier, machine_id, recorded_at) VALUES ('r1', 'code', 'measure', ?, 1)",
                 (ms.machine_row(conn),))
    rid = conn.execute("SELECT id FROM runs WHERE path = 'r1'").fetchone()[0]
    why = "w" * 300
    adopt.record(conn, adopt.Verdict("code", "old", "org/a", True, why, adopt.MEASURED), run_id=rid)
    (row,) = st.history(conn)
    assert (row["run_id"], row["why"], row["move"]) == (rid, f"code: {why}"[:200], st.ADOPT)


def test_refused_reads_the_machine_it_is_asked_about(conn):
    m2 = ms.remember_machine(conn, M2)
    conn.commit()
    _adopt(conn, "image", "org/big", how=adopt.BY_HAND, all_machines=True, size_gib=40)
    assert adopt.refused(conn) == []
    assert [r["spec"] for r in adopt.refused(conn, m2)] == ["org/big"]
    assert adopt.current(conn, m2) == {} and adopt.current(conn)["image"]["spec"] == "org/big"


def test_only_the_adoption_state_module_reads_or_writes_the_adoptions_table():
    allowed = {
        "harness/adoption_state.py": "the one writer and resolver",
        "harness/migration_check.py": "checks every row resolves, whatever the chain says",
        "harness/live_audit.py": "flags any row naming a reference model, chained or not",
        "harness/effects.py": "joins a verdict to the adoption it made, by verdict id",
    }
    hits = set()
    for path in [*(REPO / "harness").rglob("*.py"), *(REPO / "evals").rglob("*.py")]:
        rel = path.relative_to(REPO).as_posix()
        if "/migrations/" in rel or rel.startswith("harness/memory_store/"):
            continue
        if re.search(r"(?i)\b(FROM|JOIN|INTO|UPDATE)\s+adoptions\b", path.read_text(encoding="utf-8")):
            hits.add(rel)
    assert hits == set(allowed)


@pytest.mark.sqlite_store  # an old-schema store: a Postgres store starts at head. #1631.
def test_the_migration_chains_old_rows_in_the_order_they_served(tmp_path, monkeypatch):
    conftest.stand_in_machine(monkeypatch, STUDIO)
    path = tmp_path / "old.db"
    c = ms.connect(path)
    mid = ms.remember_machine(c)
    c.execute("DROP INDEX ux_adoptions_chain")
    for spec, at in (("org/a", 3.0), ("org/b", 1.0), ("org/c", 3.0)):
        c.execute("INSERT INTO adoptions (lane, candidate_id, machine_id, how, adopted_at) VALUES "
                  "('code', ?, ?, 'measured', ?)", (_cid(c, spec), mid, at))
    c.execute("INSERT INTO adoptions (lane, candidate_id, machine_id, how, adopted_at) VALUES "
              "('svg', ?, ?, 'measured', 2.0)", (_cid(c, "org/s", "svg"), mid))
    c.execute("UPDATE meta SET value = '94' WHERE key = 'schema'")
    c.commit()
    c.close()
    c = ms.connect(path)
    try:
        assert [r["spec"] for r in st.chains(c, "code")["code"]] == ["org/b", "org/a", "org/c"]
        assert st.serving(c, "code", mid, typed={}).spec == "org/c"
        assert st.off_chain(c) == []
        assert c.execute("SELECT leaves FROM adoptions WHERE lane = 'svg'").fetchone()[0] == 0
        with pytest.raises(Exception, match="UNIQUE"):
            c.execute("INSERT INTO adoptions (lane, candidate_id, how, adopted_at) VALUES ('svg', ?, 'measured', 9)",
                      (_cid(c, "org/s2", "svg"),))
    finally:
        c.close()


def test_soh_adopt_serving_and_withdraw(conn, capsys):
    from harness import cli
    _adopt(conn, "music", "org/m")
    assert cli.main(["adopt", "--json", "--serving"]) == 0
    rows = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["serving"]
    assert {(r["lane"], r["state"], r["spec"]) for r in rows} >= {("music", st.ADOPTED, "org/m")}
    assert cli.main(["adopt", "--lane", "music", "--withdraw", "too slow"]) == 0
    assert st.serving(conn, "music").state == st.WITHDRAWN
    assert cli.main(["adopt", "--lane", "music", "--withdraw", "again"]) == 1
