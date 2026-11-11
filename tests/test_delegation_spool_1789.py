"""A delegation from a checkout at another schema than the live store is spooled, and the deployed release lands it once. #1789."""
import json
import shutil

import pytest

from harness import cli, delegations, local_tools, paths
from harness.memory_store.schema import SCHEMA_VERSION
from tests.test_live_delegations_1717 import _digest, _open, _rows, elsewhere, live_pg  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

pytestmark = pytest.mark.sqlite_store


def _stamp(path, version):
    conn = _open(path)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(version),))
    conn.commit()
    conn.close()


def _skewed_delegation(live, capsys, version):
    """A delegation and its outcome from this checkout while the live store is at `version`."""
    _stamp(live, version)
    before = _digest(live)
    got = local_tools.complete(prompt="write add", lane="code")
    assert cli.main(["delegated", got["call_id"], "used", "it ran"]) == 0
    assert _digest(live) == before
    return got


@pytest.mark.parametrize("version", [SCHEMA_VERSION - 1, SCHEMA_VERSION + 1])
def test_a_checkout_at_another_schema_spools_its_rows_instead_of_dropping_them(live_pg, capsys, version):
    got = _skewed_delegation(live_pg, capsys, version)
    err = capsys.readouterr().err
    assert err.count(f"live store is at schema {version}") == 1, err
    assert "not recorded" not in err
    recs = delegations.spooled(got["call_id"])
    assert sorted(r["kind"] for r in recs) == ["delegation", "outcome", "request"]
    assert {r["schema"] for r in recs} == {SCHEMA_VERSION}
    assert len({r["id"] for r in recs}) == 3
    files = sorted(delegations.spool_dir().iterdir())
    assert len(files) == 3 and all(f.suffix == ".json" for f in files)
    assert all(len(f.read_text(encoding="utf-8").splitlines()) == 1 for f in files)
    (out,) = [r for r in recs if r["kind"] == "outcome"]
    assert (out["outcome"], out["why"]) == ("used", "it ran")
    assert _rows(live_pg, "delegations") == [] and _rows(live_pg, "gateway_requests") == []


def test_an_outcome_for_a_call_nobody_made_is_refused_not_spooled(live_pg, capsys):
    _stamp(live_pg, SCHEMA_VERSION - 1)
    assert cli.main(["delegated", "local-nope", "used"]) == 1
    said = capsys.readouterr()
    assert "no delegation has call id" in said.out + said.err
    assert delegations.spooled() == []


def test_the_drain_lands_each_record_once_however_often_it_runs(live_pg, capsys, tmp_path):
    got = _skewed_delegation(live_pg, capsys, SCHEMA_VERSION - 1)
    kept = tmp_path / "kept"
    shutil.copytree(delegations.spool_dir(), kept)
    _stamp(live_pg, SCHEMA_VERSION)
    conn = _open(live_pg)
    try:
        first = delegations.drain(conn)
        second = delegations.drain(conn)
        shutil.copytree(kept, delegations.spool_dir(), dirs_exist_ok=True)
        again = delegations.drain(conn)
    finally:
        conn.close()
    assert (first["landed"], first["duplicate"], first["held"]) == (3, 0, 0)
    assert (second["landed"], second["duplicate"], second["held"]) == (0, 0, 0)
    assert (again["landed"], again["duplicate"], again["held"]) == (0, 3, 0)
    (d,) = _rows(live_pg, "delegations")
    (r,) = _rows(live_pg, "gateway_requests")
    assert d["call_id"] == r["call_id"] == got["call_id"]
    assert (d["outcome"], d["why"]) == ("used", "it ran")
    assert list(delegations.spool_dir().iterdir()) == []


def test_a_record_naming_a_column_the_store_lacks_stays_spooled_and_held(live_pg):
    delegations.spool("delegation", call_id="local-x", row={**delegations._row("local-x", "code"), "cached": 1})
    delegations.spool("outcome", call_id="local-x", outcome="used", why="", at=1.0)
    delegations.spool("rating", call_id="local-x", stars=5)
    conn = _open(live_pg)
    try:
        got = delegations.drain(conn)
        twice = delegations.drain(conn)
    finally:
        conn.close()
    assert (got["landed"], got["held"]) == (0, 3) and twice["held"] == 3
    whys = {h["kind"]: h["why"] for h in got["held_records"]}
    assert whys["delegation"] == "columns delegations does not have here: cached"
    assert whys["outcome"] == "its delegation is not in this store yet"
    assert whys["rating"] == "a record of kind 'rating' this release does not know"
    assert len(list(delegations.spool_dir().glob("*.json"))) == 3
    assert _rows(live_pg, "delegations") == []


def test_the_hourly_close_drains_the_spool_before_it_closes(capsys):
    from harness import memory_store as ms
    ms.connect().close()
    row = delegations._row("local-y", "code", at=123.0)
    delegations.spool("delegation", call_id="local-y", row=row)
    delegations.spool("outcome", call_id="local-y", outcome="discarded", why="wrong", at=124.0)
    assert cli.main(["delegated", "--close", "--root", str(paths.home() / "none"), "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["spool"]["landed"] == 2
    conn = ms.connect()
    try:
        d = dict(conn.execute("SELECT * FROM delegations WHERE call_id = 'local-y'").fetchone())
    finally:
        conn.close()
    assert (d["outcome"], d["why"], d["outcome_at"]) == ("discarded", "wrong", 124.0)
