"""A delegation and its outcome from any home reach the live ledger through the spool while the live store is behind. #1852."""
import re

import pytest

from harness import cli, delegations, local_tools, paths, store
from harness.memory_store.schema import SCHEMA_VERSION
from tests.test_delegation_spool_1789 import _stamp
from tests.test_live_delegations_1717 import _open, _rows, elsewhere, live_pg  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

pytestmark = pytest.mark.sqlite_store
_BOUND = (paths.ENV_VAR, store.BACKEND_ENV, paths.MACHINE_FOR_ENV, paths.MACHINE_STORE_ENV)


@pytest.fixture
def behind(tmp_path, monkeypatch, live_pg):
    monkeypatch.setattr(paths, "deploy_checkout", lambda: tmp_path / "deploy")
    _stamp(live_pg, SCHEMA_VERSION - 2)
    for k in _BOUND:
        monkeypatch.delenv(k, raising=False)
    return live_pg


def _scratch(tmp_path, monkeypatch):
    home = tmp_path / "scratch"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)


def _live_env(monkeypatch):
    for k in _BOUND:
        monkeypatch.delenv(k, raising=False)


def _landed(live, call_id):
    conn = _open(live)
    try:
        got = delegations.drain(conn)
    finally:
        conn.close()
    assert got["held"] == 0, got
    (d,) = [r for r in _rows(live, "delegations") if r["call_id"] == call_id]
    return d["outcome"], d["why"]


def _ok(argv, capsys):
    rc = cli.main(argv)
    said = capsys.readouterr()
    assert rc == 0, said.out + said.err
    return said.out + said.err


def test_a_scratch_call_closed_in_the_scratch_home_lands(behind, tmp_path, monkeypatch, capsys):
    _scratch(tmp_path, monkeypatch)
    got = local_tools.complete(prompt="write add", lane="code")
    _ok(["delegated", got["call_id"], "used", "a"], capsys)
    _live_env(monkeypatch)
    assert _landed(behind, got["call_id"]) == ("used", "a")


def test_a_scratch_call_closed_from_the_live_home_lands(behind, tmp_path, monkeypatch, capsys):
    _scratch(tmp_path, monkeypatch)
    got = local_tools.complete(prompt="write add", lane="code")
    _live_env(monkeypatch)
    _ok(["delegated", got["call_id"], "edited", "b"], capsys)
    assert _landed(behind, got["call_id"]) == ("edited", "b")


def test_a_spooled_live_call_closed_from_a_scratch_home_lands(behind, tmp_path, monkeypatch, capsys):
    got = local_tools.complete(prompt="write add", lane="code")
    _scratch(tmp_path, monkeypatch)
    _ok(["delegated", got["call_id"], "discarded", "c"], capsys)
    _live_env(monkeypatch)
    assert _landed(behind, got["call_id"]) == ("discarded", "c")


def test_a_call_made_on_sqlite_in_the_live_home_closed_without_it_lands(behind, monkeypatch, capsys):
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    got = local_tools.complete(prompt="write add", lane="code")
    _live_env(monkeypatch)
    _ok(["delegated", got["call_id"], "used", "d"], capsys)
    assert _landed(behind, got["call_id"]) == ("used", "d")


@pytest.mark.skipif(not hasattr(paths, "scratch_home"), reason="soh --scratch-home is #1880")
def test_a_call_and_outcome_under_soh_scratch_home_land(behind, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(paths.MACHINE_ENV, str(paths.DEFAULT_HOME))
    where = str(tmp_path / "flagged")
    said = _ok(["--scratch-home", where, "local", "complete", "--lane", "code", "write add"], capsys)
    call_id = re.search(r"call_id (local-[0-9a-f]+)", said).group(1)
    _ok(["--scratch-home", where, "delegated", call_id, "used", "e"], capsys)
    _live_env(monkeypatch)
    assert _landed(behind, call_id) == ("used", "e")
