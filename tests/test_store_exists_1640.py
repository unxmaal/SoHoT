"""A verb handed this home's store asks the seam whether it exists, not the SQLite file a Postgres home lacks. #1640."""
import pytest

from harness import ledger, live_audit, store
from harness import memory_store as ms
from harness.commands import climb, common, knobs


class Opened(Exception):
    pass


def _opened(*a, **kw):
    raise Opened(a)


@pytest.fixture
def postgres_home(monkeypatch):
    """This home's store is Postgres and no discovery.db file exists, as after the stale pre-cutover file is gone."""
    monkeypatch.setattr(store, "home_postgres", lambda path=None: path is None or str(path) == str(ms.db_path()))
    monkeypatch.setattr(ledger, "open_ro", _opened)
    monkeypatch.setattr(store, "open_ro", _opened)
    assert not ms.db_path().exists()
    return ms.db_path()


@pytest.mark.parametrize("connect", [climb._connect, knobs._connect,
                                     lambda p: __import__("harness.lane_feed").lane_feed.open_store(p)])
def test_a_named_home_store_opens_on_a_postgres_home(postgres_home, connect):
    with pytest.raises(Opened):
        connect(str(postgres_home))


def test_yield_stop_on_the_named_home_store_reaches_the_store(postgres_home, capsys):
    a = common.parsed("yield-stop", "repo", "x", "--store", str(postgres_home))
    with pytest.raises(Opened):
        a.func(a)


def test_residency_sim_on_the_named_home_store_reaches_the_store(postgres_home):
    a = common.parsed("residency-sim", "--since", "2d", "--budget-gb", "100", "--db", str(postgres_home))
    with pytest.raises(Opened):
        a.func(a)


def test_baseline_on_this_homes_store_reaches_the_store(postgres_home, monkeypatch):
    """#1644."""
    monkeypatch.setattr(live_audit, "open_readonly", _opened)
    for argv in ([], ["--store", str(postgres_home)]):
        a = common.parsed("baseline", *argv)
        with pytest.raises(Opened):
            a.func(a)


def test_the_repo_report_lends_the_home_store_on_a_postgres_home(postgres_home, monkeypatch):
    monkeypatch.setattr(live_audit, "open_readonly", _opened)
    a = common.parsed("repo-report")
    with pytest.raises(Opened):
        a.func(a)
