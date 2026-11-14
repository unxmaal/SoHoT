"""A delegation's outcome reaches the live ledger whichever store the call or the outcome was made under. #1852."""
import json
import os

import pytest

from harness import cli, delegations, local_tools, paths, store
from tests.test_live_delegations_1717 import _open, _rows, elsewhere, live_pg  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

pytestmark = pytest.mark.sqlite_store


@pytest.fixture
def deployed(tmp_path, monkeypatch, live_pg):
    monkeypatch.setattr(paths, "deploy_checkout", lambda: tmp_path / "deploy")
    return live_pg


def _scratch(tmp_path, monkeypatch):
    home = tmp_path / "scratch"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    return home / "discovery.db"


def _live_env(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)


def _drained(live):
    conn = _open(live)
    try:
        return delegations.drain(conn)
    finally:
        conn.close()


def _said(capsys):
    got = capsys.readouterr()
    return got.out + got.err


def test_a_call_made_with_the_backend_overridden_is_closed_without_it(deployed, monkeypatch, capsys):
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    got = local_tools.complete(prompt="write add", lane="code")
    _live_env(monkeypatch)
    assert cli.main(["delegated", got["call_id"], "used", "it ran"]) == 0, _said(capsys)
    (d,) = _rows(deployed, "delegations")
    assert (d["call_id"], d["outcome"]) == (got["call_id"], "used")
    assert not (paths.DEFAULT_HOME / "discovery.db").exists()


def test_an_outcome_given_with_the_backend_overridden_reaches_the_live_store(deployed, monkeypatch, capsys):
    got = local_tools.complete(prompt="write add", lane="code")
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    assert cli.main(["delegated", got["call_id"], "edited"]) == 0, _said(capsys)
    assert [r["outcome"] for r in _rows(deployed, "delegations")] == ["edited"]


def test_a_scratch_home_call_closed_from_the_live_home_lands_in_the_ledger(deployed, tmp_path, monkeypatch, capsys):
    scratch = _scratch(tmp_path, monkeypatch)
    got = local_tools.complete(prompt="write add", lane="code")
    assert [r["call_id"] for r in _rows(scratch, "delegations")] == [got["call_id"]]
    _live_env(monkeypatch)
    assert sorted(r["kind"] for r in delegations.spooled(got["call_id"])) == ["delegation", "request"]
    assert cli.main(["delegated", got["call_id"], "used", "it ran"]) == 0, _said(capsys)
    assert _drained(deployed)["landed"] == 3
    (d,) = _rows(deployed, "delegations")
    (r,) = _rows(deployed, "gateway_requests")
    assert d["call_id"] == r["call_id"] == got["call_id"]
    assert (d["outcome"], d["why"]) == ("used", "it ran")


def test_an_outcome_given_in_the_scratch_home_reaches_the_ledger_too(deployed, tmp_path, monkeypatch, capsys):
    scratch = _scratch(tmp_path, monkeypatch)
    got = local_tools.complete(prompt="write add", lane="code")
    assert cli.main(["delegated", got["call_id"], "discarded", "wrong"]) == 0, _said(capsys)
    assert [r["outcome"] for r in _rows(scratch, "delegations")] == ["discarded"]
    _live_env(monkeypatch)
    assert _drained(deployed)["landed"] == 3
    (d,) = _rows(deployed, "delegations")
    assert (d["outcome"], d["why"]) == ("discarded", "wrong")


def test_a_live_call_closed_from_a_scratch_home_lands_in_the_ledger(deployed, tmp_path, monkeypatch, capsys):
    got = local_tools.complete(prompt="write add", lane="code")
    _scratch(tmp_path, monkeypatch)
    assert cli.main(["delegated", got["call_id"], "used"]) == 0, _said(capsys)
    _live_env(monkeypatch)
    assert _drained(deployed)["landed"] == 1
    assert [r["outcome"] for r in _rows(deployed, "delegations")] == ["used"]


def test_a_refusal_names_the_store_it_looked_in(deployed, tmp_path, monkeypatch, capsys):
    live = f"Postgres {store.pg_target(home=paths.DEFAULT_HOME)}"
    assert cli.main(["delegated", "local-nope", "used"]) == 1
    said = _said(capsys)
    assert "no delegation has call id 'local-nope'" in said and live in said, said
    scratch = _scratch(tmp_path, monkeypatch)
    assert cli.main(["delegated", "local-nope", "used"]) == 1
    said = _said(capsys)
    assert str(scratch) in said and live in said, said


@pytest.mark.parametrize("via", ["PGPORT", "store.json"])
def test_a_refusal_names_the_port_the_store_is_configured_on(deployed, monkeypatch, capsys, via):
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    if via == "PGPORT":
        monkeypatch.setenv("PGPORT", "49775")
    else:
        monkeypatch.delenv("PGPORT", raising=False)
        (paths.DEFAULT_HOME / store.MARKER).write_text(json.dumps({"backend": store.POSTGRES, "port": 49775}),
                                                      encoding="utf-8")
    assert cli.main(["delegated", "local-nope", "used"]) == 1
    assert ":49775/" in _said(capsys)
    _live_env(monkeypatch)
    assert delegations.spooled() == []


@pytest.mark.parametrize("why", ["guarded", "undeployed", "homeless"])
def test_a_scratch_call_spools_nothing_where_nothing_would_drain_it(deployed, tmp_path, monkeypatch, why):
    if why == "guarded":
        live = paths.DEFAULT_HOME
        monkeypatch.setattr(store, "guarded", lambda home: home == live)
    elif why == "undeployed":
        monkeypatch.setattr(paths, "deploy_checkout", lambda: None)
    else:
        (paths.DEFAULT_HOME / store.MARKER).unlink()
    scratch = _scratch(tmp_path, monkeypatch)
    got = local_tools.complete(prompt="write add", lane="code")
    assert [r["call_id"] for r in _rows(scratch, "delegations")] == [got["call_id"]]
    assert not (paths.DEFAULT_HOME / delegations.SPOOL).exists()


def test_the_test_run_guards_the_real_live_home_and_no_other(tmp_path):
    assert store.guarded(paths.DEFAULT_HOME)
    assert not store.guarded(tmp_path)
    assert json.loads(os.environ[store.GUARD_ENV])
