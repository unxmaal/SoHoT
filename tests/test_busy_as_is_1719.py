"""A delegation from a checkout whose schema is ahead of the live store reads its gpu lease as it stands, never migrating it. #1719."""
import os

import pytest

from harness import delegate, exclusive, item_lease, local_tools, resources
from harness import memory_store as ms
from harness.memory_store.schema import SCHEMA_VERSION
from tests.test_live_delegations_1717 import _digest, _live, _open, elsewhere  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

pytestmark = pytest.mark.sqlite_store


def _behind(path, *, lease: bool = False, drop: bool = False):
    """The live store one schema behind this checkout, optionally with a gpu lease or with no leases table."""
    conn = _open(path)
    if lease:
        conn.close()
        conn = ms.connect(path)
        item_lease.take(conn, resources.GPU, f"image pid {os.getpid()}", state="image", detail="image")
    if drop:
        conn.execute("DROP TABLE leases")
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION - 1),))
    conn.commit()
    conn.close()
    return _digest(path)


def _schema(path):
    conn = _open(path)
    try:
        return int(conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()["value"])
    finally:
        conn.close()


@pytest.fixture
def ahead(tmp_path, monkeypatch, elsewhere):  # noqa: F811
    path = tmp_path / "made" / "discovery.db"
    ms.connect(path).close()
    return path


def _seat(tmp_path, monkeypatch, made):
    live = _live(tmp_path, monkeypatch)
    live.write_bytes(made.read_bytes())
    return live


def test_a_delegation_ahead_of_the_live_schema_is_not_refused_and_nothing_migrates(ahead, tmp_path, monkeypatch, capsys):
    before = _behind(ahead)
    live = _seat(tmp_path, monkeypatch, ahead)
    got = local_tools.complete(prompt="write add", lane="code")
    assert got["text"] and got["call_id"]
    assert _digest(live) == before and _schema(live) == SCHEMA_VERSION - 1
    assert "refused" not in capsys.readouterr().err


def test_a_gpu_lease_in_a_store_behind_this_checkout_is_still_named(ahead, tmp_path, monkeypatch):
    before = _behind(ahead, lease=True)
    live = _seat(tmp_path, monkeypatch, ahead)
    assert "image" in delegate.busy() and "image" in delegate.held_now()
    assert _digest(live) == before


def test_a_lease_table_it_cannot_read_says_so_and_is_not_busy(ahead, tmp_path, monkeypatch, capsys):
    before = _behind(ahead, drop=True)
    live = _seat(tmp_path, monkeypatch, ahead)
    assert delegate.held_now() == ""
    err = capsys.readouterr().err
    assert "not known to be busy" in err and "leases" in err
    assert _digest(live) == before


def test_a_live_store_that_will_not_open_still_refuses(tmp_path, monkeypatch, elsewhere):  # noqa: F811
    live = _live(tmp_path, monkeypatch)
    live.unlink()
    live.mkdir()
    with pytest.raises(exclusive.StoreDown):
        exclusive.gpu_holder(as_is=True)
    with pytest.raises(delegate.Refused, match="unreachable"):
        delegate.held_now()


def test_the_deploy_checkout_keeps_its_own_store_path(tmp_path, monkeypatch, elsewhere):  # noqa: F811
    _live(tmp_path, monkeypatch)
    monkeypatch.setattr(exclusive, "_as_is", lambda: pytest.fail("the deploy checkout read the store as it stands"))
    monkeypatch.setattr("harness.paths.runs_elsewhere", lambda: None)
    assert delegate.busy() == ""
