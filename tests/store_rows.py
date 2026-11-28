"""Every row of every table in an open store, whichever backend it is, so a test can say a call wrote nothing."""
from harness import store


def dump(conn) -> dict:
    if store.dialect(conn) == store.POSTGRES:
        sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
    else:
        sql = "SELECT name FROM sqlite_master WHERE type = 'table'"
    names = sorted(r[0] for r in conn.execute(sql).fetchall())
    out = {}
    for name in names:
        rows = conn.execute(f'SELECT * FROM "{name}"').fetchall()
        out[name] = sorted(repr([r[k] for k in r.keys()]) for r in rows)
    return out
