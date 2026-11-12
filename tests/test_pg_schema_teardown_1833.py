import pytest

from harness import store
from tests import conftest


def _exists(dsn, name):
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute("SELECT to_regnamespace(%s) IS NOT NULL", (name,)).fetchone()[0]


@pytest.mark.postgres
def test_the_schema_is_dropped_on_its_own_server_though_the_test_moved_pg_variables(monkeypatch):
    if store.backend() != store.POSTGRES:
        pytest.skip("needs a live Postgres: make test-postgres")
    real = store.dsn()
    with monkeypatch.context() as m:
        with conftest.own_schema(m) as name:
            assert _exists(real, name)
            m.setenv("PGHOST", "127.0.0.1")
            m.setenv("PGPORT", "1")
            m.setenv("PGDATABASE", "nowhere")
    assert not _exists(real, name)
    assert store.REFUSALS == []
