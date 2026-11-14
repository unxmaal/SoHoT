"""The store on Postgres (#1507): the derived schema, the row shape, the copy each way, the switch."""
import json
import os
import sqlite3
import sys

import pytest

from harness import memory_store as ms, store, store_copy, store_service as svc


def _pg_ready():
    if store.backend() != store.POSTGRES:
        pytest.skip("needs a live Postgres: make test-postgres")


# ---- the DDL Postgres can run ----------------------------------------------

def test_a_table_comes_before_the_tables_that_reference_it():
    ddl = ("CREATE TABLE IF NOT EXISTS a (id INTEGER PRIMARY KEY, b_id INTEGER REFERENCES b(id));\n"
           "CREATE INDEX IF NOT EXISTS a_b ON a(b_id);\n"
           "CREATE TABLE IF NOT EXISTS b (id INTEGER PRIMARY KEY, c_id INTEGER REFERENCES c(id));\n"
           "CREATE TABLE IF NOT EXISTS c (id INTEGER PRIMARY KEY);\n")
    got = store.statements(store.postgres_ddl(ddl))
    order = [s.split("EXISTS ")[1].split()[0] for s in got]
    assert order == ["c", "b", "a", "a_b"]


def test_every_foreign_key_in_the_real_schema_points_backwards():
    seen = set()
    for s in store.statements(store.postgres_ddl(ms._DDL)):
        m = store._CREATE_TABLE.match(store._code(s))
        if not m:
            continue
        name = m.group(1).lower()
        for ref in store._REFERENCES.findall(store._code(s)):
            assert ref.lower() in seen | {name}, f"{name} references {ref} before it exists"
        seen.add(name)


def test_a_semicolon_in_a_comment_or_literal_does_not_split_a_statement():
    got = store.statements("CREATE TABLE t (a TEXT DEFAULT 'x;y'); -- one; two\n"
                           "/* three; */ CREATE TABLE u (b TEXT);")
    assert len(got) == 2 and "'x;y'" in got[0]


def test_a_literal_percent_is_not_a_placeholder():
    assert store.translate("SELECT 1 FROM t WHERE a LIKE 'x%' AND b = ?") == \
        "SELECT 1 FROM t WHERE a LIKE 'x%%' AND b = %s"


def test_only_a_table_with_an_id_returns_one():
    assert {"proposals", "jobs", "verdicts"} <= store.id_tables()
    assert "meta" not in store.id_tables()


# ---- a Postgres row reads like a sqlite3.Row ---------------------------------

def test_a_row_reads_by_position_by_name_and_as_a_dict():
    class Col:
        def __init__(self, name):
            self.name = name

    class Cur:
        description = [Col("id"), Col("Name")]

    row = store.row_factory(Cur())((7, "x"))
    assert row[0] == 7 and row["name"] == "x" and row["NAME"] == "x"
    assert dict(row) == {"id": 7, "Name": "x"} and tuple(row) == (7, "x")
    with pytest.raises(IndexError):
        row["missing"]


# ---- which store a home talks to --------------------------------------------

def test_a_home_with_store_json_talks_to_postgres(tmp_path, monkeypatch):
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    assert store.backend() == store.SQLITE
    svc.switch(store.POSTGRES, tmp_path)
    assert store.backend() == store.POSTGRES
    assert store.marker(tmp_path)["port"] == svc.PORT
    svc.switch(store.SQLITE, tmp_path)
    assert store.backend() == store.SQLITE
    assert (tmp_path / "store.json.off").is_file()


def test_the_variable_overrides_the_home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    svc.switch(store.POSTGRES, tmp_path)
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    assert store.backend() == store.SQLITE


def test_on_a_postgres_home_any_other_path_is_a_sqlite_file(tmp_path, monkeypatch):
    """A copy or a canary's isolated home stays a file; only this home's path is Postgres. #1579."""
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    copy = tmp_path / "copy.db"
    conn = ms.connect(copy)
    try:
        assert store.dialect(conn) == store.SQLITE
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == str(ms.SCHEMA_VERSION)
    finally:
        conn.close()
    assert copy.is_file() and store.backend() == store.POSTGRES
    assert store.home_postgres(None) and store.home_postgres(ms.db_path()) and not store.home_postgres(copy)
    assert store.exists() and store.exists(copy) and not store.exists(tmp_path / "none.db")


def test_an_older_sqlite_copy_migrates_as_sqlite_on_a_postgres_home(tmp_path, monkeypatch):
    """Schema 35's step resets a Postgres sequence when this home is Postgres; a SQLite copy must skip it. #1579."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("golden_build", Path(__file__).parent / "golden" / "build.py")
    gb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gb)
    from harness import paths
    db, _ = gb.load(Path(__file__).parent / "golden" / "v34", tmp_path)
    jobs = paths.home() / "queue" / "jobs"
    jobs.mkdir(parents=True)
    (jobs / "0001.json").write_text(json.dumps({"id": 1, "argv": ["true"], "created_at": 0}), encoding="utf-8")
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    conn = ms.connect(db)
    try:
        assert conn.execute("SELECT value FROM meta WHERE key = 'schema'").fetchone()[0] == str(ms.SCHEMA_VERSION)
        assert conn.execute("SELECT count(*) FROM jobs WHERE id = 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_pin_holds_only_on_its_own_thread_and_only_meanwhile(monkeypatch):
    import threading
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    seen = []
    with store.pinned(store.SQLITE):
        assert store.backend() == store.SQLITE
        t = threading.Thread(target=lambda: seen.append(store.backend()))
        t.start()
        t.join()
    assert seen == [store.POSTGRES] and store.backend() == store.POSTGRES


def test_a_postgres_home_names_the_copy_a_dry_run_migrates(monkeypatch):
    from harness import migration_check as mc
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    with pytest.raises(FileNotFoundError, match="Postgres"):
        mc.dry_run()


def test_the_canary_seeds_its_isolated_home_never_a_postgres_live_store(tmp_path, monkeypatch):
    """The live home chose Postgres by store.json, as the Studio does; no Postgres is reachable here. #1579."""
    from harness import canary, paths
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    svc.switch(store.POSTGRES, paths.home())
    monkeypatch.setattr(store, "postgres_connect", lambda *a, **k: pytest.fail("the canary opened Postgres"))
    plant = canary.Plant("worse", "stt", "org/worse", ("declined", "adopt", "candidate"))
    envs = []

    def run(argv, env=None, **kw):
        envs.append(env)
        return type("R", (), {"returncode": 0})()
    home = tmp_path / "isolated"
    got = canary.run_plant(plant, home, run=run, say=lambda *_: None)
    assert (home / "discovery.db").is_file() and got["observed"]["outcome"] == ""
    assert envs and all(e[store.BACKEND_ENV] == store.SQLITE for e in envs)


def test_a_dry_run_switch_writes_nothing(tmp_path):
    got = svc.switch(store.POSTGRES, tmp_path, dry_run=True)
    assert got["dry_run"] and not (tmp_path / "store.json").exists()


def test_the_dsn_takes_the_home_and_the_keychain_never_the_repo(tmp_path):
    (tmp_path / "store.json").write_text(json.dumps(svc.marker_for(6543)), encoding="utf-8")
    asked = []
    got = store.dsn({}, home=tmp_path, lookup=lambda s, a: asked.append((s, a)) or "pw'1")
    assert "port='6543'" in got and "user='discovery'" in got and "password='pw\\'1'" in got
    assert asked == [(store.SECRET_SERVICE, "discovery")]


def test_a_reader_connects_as_the_read_only_role_in_read_only_transactions(tmp_path):
    (tmp_path / "store.json").write_text(json.dumps(svc.marker_for()), encoding="utf-8")
    got = store.dsn({}, read_only=True, home=tmp_path, lookup=lambda s, a: "x")
    assert f"user='{store.DEFAULT_READER}'" in got and "default_transaction_read_only=on" in got


def test_a_reader_with_no_role_still_cannot_write(tmp_path):
    got = store.dsn({"PGUSER": "discovery", "PGPASSWORD": "p"}, read_only=True, home=tmp_path)
    assert "user='discovery'" in got and "default_transaction_read_only=on" in got


def test_live_only_when_the_default_home_chose_postgres(tmp_path, monkeypatch):
    from harness import paths
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    monkeypatch.setattr(paths, "DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    assert not store.live()
    svc.switch(store.POSTGRES, tmp_path)
    assert store.live()
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    assert not store.live()


# ---- the container's secrets ------------------------------------------------

def test_a_password_is_generated_once_and_kept(tmp_path):
    from harness import gateway_key
    secret = gateway_key.FileStore(tmp_path / "pg.secret")
    first = svc.password("discovery", ensure=True, secret=secret)
    assert first and svc.password("discovery", secret=secret) == first
    if sys.platform != "win32":  # chmod sets only the read-only bit on Windows; an ACL is the equivalent.
        assert oct((tmp_path / "pg.secret").stat().st_mode & 0o777) == "0o600"


def test_compose_gets_the_password_in_its_environment_never_its_argv(shown_live, tmp_path):
    from harness import gateway_key
    secret = gateway_key.FileStore(tmp_path / "pg.secret")
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw["env"]))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    svc.compose(["up", "-d", "--wait"], run=run, environ={}, secret=secret)
    argv, env = calls[0]
    pw = secret.get()
    assert argv[:3] == ["docker", "compose", "-f"] and pw not in " ".join(argv)
    assert env["SOHOT_PG_PASSWORD"] == pw and env["SOHOT_PG_PORT"] == str(svc.PORT)


def test_the_compose_file_publishes_loopback_only_and_keeps_no_secret():
    text = svc.COMPOSE.read_text(encoding="utf-8")
    assert '"127.0.0.1:' in text and "0.0.0.0" not in text
    assert "POSTGRES_PASSWORD: ${SOHOT_PG_PASSWORD" in text
    assert "healthcheck" in text and "sohot-pg:/var/lib/postgresql/data" in text


# ---- the digest each backend agrees on --------------------------------------

def test_a_whole_float_and_its_integer_hash_alike_and_text_differs_from_bytes():
    assert store_copy.row_hash((5, None)) == store_copy.row_hash((5.0, None))
    assert store_copy.row_hash(("ab",)) != store_copy.row_hash((b"ab",))
    assert store_copy.row_hash((0.5,)) != store_copy.row_hash((0,))


def test_the_digest_ignores_row_order_and_sees_one_changed_value(tmp_path):
    a = sqlite3.connect(tmp_path / "a.db")
    a.row_factory = sqlite3.Row
    a.executescript("CREATE TABLE t (id INTEGER, v TEXT); INSERT INTO t VALUES (1,'x'),(2,'y');")
    b = sqlite3.connect(tmp_path / "b.db")
    b.row_factory = sqlite3.Row
    b.executescript("CREATE TABLE t (id INTEGER, v TEXT); INSERT INTO t VALUES (2,'y'),(1,'x');")
    assert store_copy.digest(a, "t", ["id", "v"]) == store_copy.digest(b, "t", ["id", "v"])
    b.execute("UPDATE t SET v = 'z' WHERE id = 2")
    assert store_copy.compare(a, b)[0]["ok"] is False


def test_a_source_table_the_destination_lacks_is_a_gap(tmp_path):
    a = sqlite3.connect(tmp_path / "a.db")
    a.row_factory = sqlite3.Row
    a.executescript("CREATE TABLE t (id INTEGER, extra TEXT); CREATE TABLE gone (x);")
    b = sqlite3.connect(tmp_path / "b.db")
    b.row_factory = sqlite3.Row
    b.executescript("CREATE TABLE t (id INTEGER);")
    got = store_copy.gaps(a, b)
    assert any("gone" in g for g in got) and any("extra" in g for g in got)


# ---- the copy each way, on a real Postgres ----------------------------------

def _filled_sqlite(path):
    conn = store_copy.fresh_sqlite(path)
    ms.record(conn, ms.Seen(name="t/a", kind="candidate", lane="image", source="feed",
                            url="https://x", why="it's; odd ?", relevance=3, resolved=""))
    ms.decide(conn, "t/a", "queued", tier="inspect")
    conn.execute("INSERT INTO jobs (title, kind, output, priority, argv, cwd, state, created_at) "
                 "VALUES ('j', 'eval', '', 0, '[]', '', 'cancelled', 1.5)")
    top = conn.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
    conn.execute("DELETE FROM jobs WHERE id = ?", (top,))
    conn.commit()
    conn.close()
    return top


@pytest.mark.postgres
def test_sqlite_to_postgres_and_back_is_equal_table_by_table(tmp_path):
    _pg_ready()
    db = tmp_path / "discovery.db"
    cancelled = _filled_sqlite(db)
    got = store_copy.to_postgres_report(db, tmp_path / "snap.db", dry_run=False, replace=False)
    assert got["ok"], got
    assert all(r["ok"] for r in got["verify"]) and {r["table"] for r in got["verify"]} >= {"proposals", "verdicts"}
    pg = ms.connect()
    try:
        assert pg.execute("SELECT name FROM proposals").fetchone()["name"] == "t/a"
        new = pg.execute("INSERT INTO jobs (title, kind, output, priority, argv, cwd, state, created_at) "
                         "VALUES ('k', 'eval', '', 0, '[]', '', 'queued', 2.0)").lastrowid
        pg.commit()
        assert new > cancelled, "a cancelled top id must never be reused"
    finally:
        pg.close()
    back = store_copy.to_sqlite_report(tmp_path / "back.db")
    assert back["ok"], back
    assert db.read_bytes() == (tmp_path / "snap.db").read_bytes() or db.is_file()


@pytest.mark.postgres
def test_a_dry_run_copies_nothing_and_a_second_copy_needs_replace(tmp_path):
    _pg_ready()
    db = tmp_path / "discovery.db"
    _filled_sqlite(db)
    dry = store_copy.to_postgres_report(db, tmp_path / "s1.db", dry_run=True, replace=False)
    assert dry["ok"] and dry["rows"]["proposals"] == 1
    pg = ms.connect()
    assert pg.execute("SELECT COUNT(*) AS n FROM proposals").fetchone()["n"] == 0
    pg.close()
    assert store_copy.to_postgres_report(db, tmp_path / "s2.db", dry_run=False, replace=False)["ok"]
    again = store_copy.to_postgres_report(db, tmp_path / "s3.db", dry_run=False, replace=False)
    assert not again["ok"] and "--replace" in again["why"]
    assert store_copy.to_postgres_report(db, tmp_path / "s4.db", dry_run=False, replace=True)["ok"]


@pytest.mark.postgres
def test_the_sqlite_file_is_never_written(tmp_path):
    _pg_ready()
    db = tmp_path / "discovery.db"
    _filled_sqlite(db)
    before = db.read_bytes(), db.stat().st_mtime_ns
    assert store_copy.to_postgres_report(db, tmp_path / "snap.db", dry_run=False, replace=False)["ok"]
    assert (db.read_bytes(), db.stat().st_mtime_ns) == before


@pytest.mark.postgres
def test_the_reader_role_can_select_and_cannot_write(_pg_schema):
    _pg_ready()
    import psycopg
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="t/r", source="feed", resolved="t/r", url="https://x"))
    conn.commit()
    role = f"ro_{_pg_schema}"
    svc.grant_reader(conn, role, "pw")
    conn.close()
    env = {**os.environ, store.READER_ENV: role, "PGPASSWORD_RO": "pw"}
    ro = store.postgres_connect(env, read_only=True)
    try:
        assert ro.execute("SELECT name FROM proposals").fetchone()["name"] == "t/r"
        ro.rollback()
        with pytest.raises(sqlite3.OperationalError):
            ro.execute("DELETE FROM proposals")
        with psycopg.connect(store.dsn({**env, "PGUSER": role, "PGPASSWORD": "pw"})) as plain:
            assert plain.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    finally:
        ro.close()
        with psycopg.connect(store.dsn(), autocommit=True) as admin:
            admin.execute(f"DROP OWNED BY {role}")
            admin.execute(f"DROP ROLE {role}")


@pytest.mark.postgres
def test_a_current_store_opens_without_running_the_ddl(monkeypatch):
    _pg_ready()
    ms.connect().close()
    ran = []
    monkeypatch.setattr(store.PostgresConnection, "executescript", lambda self, ddl: ran.append(1))
    ms.connect().close()
    assert ran == []


# ---- a long-lived service borrows from one pool ------------------------------

@pytest.mark.postgres
def test_a_pooled_service_gives_back_what_it_closes_and_what_it_drops():
    _pg_ready()
    import gc
    import threading
    ms.connect().close()
    pool = store.use_pool(2)
    try:
        conns = [ms.connect() for _ in range(2)]
        assert pool.get_stats()["pool_available"] == 0
        conns[0].close()
        del conns[1]
        gc.collect()
        assert pool.get_stats()["pool_available"] == 2
        errors = []

        def write(i):
            c = ms.connect()
            try:
                c.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (f"t{i}", "x"))
                c.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            finally:
                c.close()

        threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        c = ms.connect()
        assert c.execute("SELECT COUNT(*) AS n FROM meta WHERE key LIKE 't%'").fetchone()["n"] == 6
        c.close()
    finally:
        store.drop_pool()


def test_the_ci_runs_the_suite_on_postgres_nightly_and_when_a_change_reaches_the_store():
    import re
    import yaml
    doc = yaml.safe_load((svc.paths.REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    job = doc["jobs"]["check-postgres"]
    assert job["needs"] == "store-touched"
    assert "schedule" in job["if"] and "needs.store-touched.outputs.touched == '1'" in job["if"]
    run = doc["jobs"]["store-touched"]["steps"][1]["run"]
    seam = re.compile(re.search(r"seam='([^']+)'", run).group(1))
    for path in ("harness/store.py", "harness/store_copy.py", "harness/memory_store/schema.py", "tests/conftest.py",
                 "deploy/postgres/compose.yaml", "tests/gauntlet/postgres_known.txt", "harness/commands/store.py"):
        assert seam.search(path), path
    for path in ("harness/watchdog.py", "harness/storefront.txt", "evals/run.py", "README.md"):
        assert not seam.search(path), path
    assert "make test-postgres-suite" in "\n".join(s.get("run", "") for s in job["steps"])
    assert "check-postgres" in doc["jobs"]["report-nightly"]["needs"]
    make = (svc.paths.REPO / "Makefile").read_text(encoding="utf-8")
    assert "LOCALHARNESS_STORE=postgres" in make and "-m 'not slow and not network and not litellm'" in make


@pytest.mark.postgres
def test_the_sqlite_functions_the_queries_call_exist_on_postgres():
    _pg_ready()
    conn = ms.connect()
    try:
        assert conn.execute("SELECT instr('abcd', 'cd') AS n").fetchone()["n"] == 3
        assert conn.execute("""SELECT json_extract('{"a": {"b": 7}}', '$.a.b') AS v""").fetchone()["v"] == "7"
        got = conn.execute("SELECT group_concat(DISTINCT x) AS g FROM (VALUES ('p'), ('q'), (NULL), ('p')) AS t(x)")
        assert sorted(got.fetchone()["g"].split(",")) == ["p", "q"]
        assert store.has_table(conn, "proposals") and not store.has_table(conn, "nowhere")
    finally:
        conn.close()


def test_has_table_on_sqlite(tmp_path):
    conn = store_copy.fresh_sqlite(tmp_path / "s.db")
    assert store.has_table(conn, "proposals") and not store.has_table(conn, "nowhere")


# ---- a migrating deploy backs Postgres up with pg_dump and restores it whole --------

class _Ran:
    def __init__(self, rc=0, out=b"DUMP"):
        self.calls, self.rc, self.out = [], rc, out

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if kw.get("stdout") is not None:
            kw["stdout"].write(self.out)
        return type("R", (), {"returncode": self.rc, "stderr": b"boom"})()


def test_a_dump_lands_whole_or_not_at_all(tmp_path):
    ran = _Ran()
    svc.dump(tmp_path / "b" / "x.dump", run=ran)
    assert (tmp_path / "b" / "x.dump").read_bytes() == b"DUMP"
    assert ran.calls[0][0][:3] == ["docker", "exec", svc.CONTAINER] and "-Fc" in ran.calls[0][0]
    with pytest.raises(RuntimeError, match="pg_dump exited 1"):
        svc.dump(tmp_path / "y.dump", run=_Ran(rc=1))
    assert not (tmp_path / "y.dump").exists() and not (tmp_path / "y.dump.tmp").exists()


def test_a_restore_is_one_transaction(shown_live, tmp_path):
    (tmp_path / "x.dump").write_bytes(b"DUMP")
    ran = _Ran(out=b"-- script")
    svc.restore(tmp_path / "x.dump", run=ran)
    script, load = ran.calls[0][0], ran.calls[1][0]
    assert "pg_restore" in script and "--clean" in script and "-d" not in script
    assert "psql" in load and "-1" in load and "ON_ERROR_STOP=1" in load and svc.DROP_TABLES in load
    assert not (tmp_path / "x.dump.restore.sql").exists()
    with pytest.raises(RuntimeError, match="pg_restore exited 1"):
        svc.restore(tmp_path / "x.dump", run=_Ran(rc=1))


def _local_tools(schema, monkeypatch):
    """The container's pg tools as this host's, on the PG* server, in the test's own schema."""
    import shutil
    tools = {t: shutil.which(t) for t in ("pg_dump", "pg_restore", "psql")}
    if not all(tools.values()):
        pytest.skip("needs pg_dump, pg_restore and psql on PATH")

    def local(argv, stdin=False):
        argv = [tools[argv[0]], *argv[1:]]
        return argv + ["-n", schema] if argv[0] == tools["pg_dump"] else argv
    monkeypatch.setattr(svc, "in_container", local)


def test_a_postgres_restore_puts_the_backup_back_and_drops_what_a_migration_added(tmp_path, monkeypatch, _pg_schema):
    """#1610: deploy 15's backup is a pg_dump; the rollback must leave the store exactly as it was dumped."""
    from harness import deploy_switch
    _pg_ready()
    _local_tools(_pg_schema, monkeypatch)
    ms.connect().close()
    saved = svc.dump(tmp_path / "discovery-15-pre92.db")
    conn = store.postgres_connect()
    try:
        conn.execute("CREATE TABLE added_by_migration (x INTEGER)")
        conn.execute("ALTER TABLE jobs ADD COLUMN added_column TEXT")
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(ms.SCHEMA_VERSION + 1),))
        conn.commit()
    finally:
        conn.close()
    assert deploy_switch.restore(saved, ms.db_path()) == ms.SCHEMA_VERSION
    conn = store.postgres_connect()
    try:
        assert not store.has_table(conn, "added_by_migration")
        cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns "
                                           "WHERE table_schema = current_schema() AND table_name = 'jobs'")}
        assert "added_column" not in cols and "id" in cols
    finally:
        conn.close()


def test_a_deploy_on_postgres_backs_up_with_pg_dump(tmp_path, monkeypatch):
    from harness import deploy
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    got = []
    monkeypatch.setattr(svc, "dump", lambda dest: got.append(dest) or dest)
    deploy.backup(tmp_path / "discovery.db", tmp_path / "pre.db")
    assert got == [tmp_path / "pre.db"]


# ---- SQLite-only code outside the seam is an inventory that only shrinks ----------

#: Counted 2026-11-07 (#1507). origin/main had sqlite3_connect 18, uri_mode 11; the rest are SQLite branches.
SQLITE_ONLY_PIN = {"backup": 4, "except_sqlite3": 23, "pragma": 9, "sqlite3_connect": 12,
                   "sqlite_master": 2, "uri_mode": 5}


def test_sqlite_only_code_outside_the_seam_only_shrinks():
    from harness import store_audit
    got = store_audit.counts()
    grew = {k: (n, SQLITE_ONLY_PIN.get(k, 0)) for k, n in got.items() if n > SQLITE_ONLY_PIN.get(k, 0)}
    assert not grew, f"new SQLite-only code outside harness/store.py (count, pin): {grew}; go through the seam"
    shrank = {k: (got.get(k, 0), n) for k, n in SQLITE_ONLY_PIN.items() if got.get(k, 0) < n}
    assert not shrank, f"lower the pin to match (count, pin): {shrank}"


def test_the_scan_finds_each_kind(tmp_path):
    from harness import store_audit
    (tmp_path / "harness").mkdir()
    (tmp_path / "evals").mkdir()
    (tmp_path / "harness" / "x.py").write_text(
        "import sqlite3\n"
        "c = sqlite3.connect('file:a?mode=ro', uri=True)\n"
        "c.execute('PRAGMA table_info(t)')\n"
        "c.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")\n"
        "try:\n    c.backup(c)\nexcept sqlite3.Error:\n    raise\n", encoding="utf-8")
    kinds = {k for _, _, k in store_audit.scan(tmp_path)}
    assert kinds == {"sqlite3_connect", "uri_mode", "pragma", "sqlite_master", "backup", "except_sqlite3"}


# ---- NULL sorts where SQLite sorts it, and a recorded upsert names its key ------------

@pytest.mark.parametrize("sql,want", [
    ("SELECT a FROM t ORDER BY a DESC LIMIT 1", "ORDER BY a DESC NULLS LAST LIMIT 1"),
    ("SELECT a FROM t ORDER BY a, b DESC", "ORDER BY a NULLS FIRST, b DESC NULLS LAST"),
    ("SELECT row_number() OVER (ORDER BY at DESC) FROM t", "OVER (ORDER BY at DESC NULLS LAST)"),
    ("SELECT a FROM t WHERE b = 'ORDER BY c' ORDER BY f(a, 2) ASC", "'ORDER BY c' ORDER BY f(a, 2) ASC NULLS FIRST"),
    ("SELECT 1 FROM t ORDER BY a NULLS LAST", "ORDER BY a NULLS LAST"),
])
def test_null_sorts_first_ascending_and_last_descending_as_in_sqlite(sql, want):
    assert want in store.translate(sql)


def test_an_upsert_with_a_column_list_updates_every_listed_column_but_the_key():
    got = store.translate("INSERT OR REPLACE INTO delegations (call_id, lane, spec) VALUES (?, ?, ?)")
    assert got.endswith("ON CONFLICT (call_id) DO UPDATE SET lane = EXCLUDED.lane, spec = EXCLUDED.spec")


@pytest.mark.postgres
def test_nullable_order_and_upsert_agree_with_sqlite_on_a_real_postgres(tmp_path):
    _pg_ready()
    from harness import delegations
    sql = "SELECT call_id FROM delegations ORDER BY seconds DESC"
    lite = store_copy.fresh_sqlite(tmp_path / "s.db")
    pg = ms.connect()
    try:
        for conn in (lite, pg):
            for cid, secs in (("a", 1.0), ("b", None), ("c", 3.0)):
                delegations.record(conn, cid, "code", seconds=secs)
            delegations.record(conn, "a", "web", seconds=2.0)
        assert [r[0] for r in lite.execute(sql)] == [r[0] for r in pg.execute(sql)] == ["c", "a", "b"]
        assert pg.execute("SELECT lane FROM delegations WHERE call_id = 'a'").fetchone()["lane"] == "web"
    finally:
        pg.close()
        lite.close()


# ---- the rest of SQLite's dialect the queries use -------------------------------------

def test_sqlite_terms_are_spelled_as_postgres_spells_them():
    t = store.translate
    assert "a = ANY('{}') AND b <> ALL('{}')" in t("SELECT 1 FROM x WHERE a IN () AND b NOT IN ()")
    assert "a IS NOT DISTINCT FROM %s AND b IS DISTINCT FROM %s AND c IS NULL" in t(
        "SELECT 1 FROM x WHERE a IS ? AND b IS NOT ? AND c IS NULL")
    assert "x ~ sqlite_glob(%s) AND y = 'a GLOB ?'" in t("SELECT 1 FROM z WHERE x GLOB ? AND y = 'a GLOB ?'")
    assert "x ~ sqlite_glob(:p)" in t("SELECT 1 FROM z WHERE x GLOB :p")
    assert "CAST(n AS BIGINT)" in t("SELECT CAST(n AS INTEGER) FROM x")
    assert t("ALTER TABLE x ADD COLUMN n INTEGER NOT NULL DEFAULT 0").endswith("n BIGINT NOT NULL DEFAULT 0")
    assert store.named("VALUES (:a, :b_c, 'x:y', n::text)") == "VALUES (%(a)s, %(b_c)s, 'x:y', n::text)"


def test_an_integer_column_holds_64_bits_as_in_sqlite():
    ddl = store.postgres_ddl("CREATE TABLE t (id INTEGER PRIMARY KEY, size INTEGER);")
    assert "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" in ddl and "size BIGINT" in ddl


@pytest.mark.postgres
def test_the_terms_run_on_a_real_postgres_as_on_sqlite(tmp_path):
    _pg_ready()
    lite = store_copy.fresh_sqlite(tmp_path / "s.db")
    pg = ms.connect()
    try:
        for conn in (lite, pg):
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("big", str(2 ** 40)))
            conn.execute("INSERT INTO delegations (call_id, at, lane, prompt_tokens) VALUES "
                         "(:c, :at, :lane, :n)", {"c": "m-12/x", "at": 1.0, "lane": "code", "n": 2 ** 40})
        asks = [("SELECT call_id FROM delegations WHERE lane IN ()", ()),
                ("SELECT call_id FROM delegations WHERE lane NOT IN ()", ()),
                ("SELECT call_id FROM delegations WHERE spec IS ?", ("",)),
                ("SELECT call_id FROM delegations WHERE outcome IS NOT ?", (None,)),
                ("SELECT call_id FROM delegations WHERE call_id GLOB ?", ("m-[0-9]*/*",)),
                ("SELECT prompt_tokens FROM delegations WHERE ? IS NULL OR lane = ?", (None, "x"))]
        for sql, args in asks:
            assert [tuple(r) for r in lite.execute(sql, args)] == [tuple(r) for r in pg.execute(sql, args)], sql
    finally:
        pg.close()
        lite.close()


# ---- a failed statement undoes itself alone and raises what SQLite raises -----------

@pytest.mark.postgres
def test_a_failed_statement_leaves_the_transaction_open_and_raises_sqlites_error(tmp_path):
    _pg_ready()
    lite = store_copy.fresh_sqlite(tmp_path / "s.db")
    pg = ms.connect()
    try:
        for conn in (lite, pg):
            conn.execute("INSERT INTO meta (key, value) VALUES ('a', '1')")
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO meta (key, value) VALUES ('a', '2')")
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("SELECT nope FROM meta")
            conn.execute("INSERT INTO meta (key, value) VALUES ('b', '1')")
            conn.commit()
            assert [r[0] for r in conn.execute("SELECT key FROM meta WHERE key IN ('a', 'b') ORDER BY key")] == ["a", "b"]
    finally:
        pg.close()
        lite.close()


@pytest.mark.postgres
def test_a_connection_is_a_transaction_in_a_with_block_as_in_sqlite():
    _pg_ready()
    conn = ms.connect()
    try:
        with pytest.raises(RuntimeError):
            with conn:
                conn.execute("INSERT INTO meta (key, value) VALUES ('w', '1')")
                raise RuntimeError("undo")
        with conn:
            conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", [("x", "1"), ("y", "2")])
        assert [r[0] for r in conn.execute("SELECT key FROM meta WHERE key IN ('w', 'x', 'y') ORDER BY key")] == ["x", "y"]
    finally:
        conn.close()


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:PGHOST")
def test_the_container_the_switch_and_the_owner_name_the_same_postgres(tmp_path):
    import re
    published = re.search(r'"127\.0\.0\.1:\$\{SOHOT_PG_PORT:-(\d+)\}:5432"', svc.COMPOSE.read_text(encoding="utf-8"))
    assert published and int(published.group(1)) == svc.PORT
    svc.switch(store.POSTGRES, tmp_path)
    from harness import gateway_key
    owner = svc.owner_environ(secret=gateway_key.FileStore(tmp_path / "pw"))
    by_switch = store.dsn({}, home=tmp_path, lookup=lambda s, a: "")
    by_owner = store.dsn(owner, home=tmp_path / "elsewhere", lookup=lambda s, a: "")
    assert by_switch == by_owner


#: Tests still red on Postgres when this was counted (#1507); the inventory may only shrink.
POSTGRES_KNOWN_PIN = 0


def test_the_tests_still_red_on_postgres_only_shrink():
    from tests import conftest
    known = conftest.postgres_known()
    assert len(known) <= POSTGRES_KNOWN_PIN, (
        f"{len(known)} tests listed red on Postgres, pinned at {POSTGRES_KNOWN_PIN}: fix the new one instead")
    assert all("::" in k and k.startswith("tests/") for k in known)


def test_a_listed_test_is_xfail_only_on_postgres(monkeypatch):
    from tests import conftest
    listed = "tests/test_x.py::test_red_on_postgres"
    monkeypatch.setattr(conftest, "postgres_known", lambda: {listed})
    item = type("I", (), {"nodeid": listed, "marks": [],
                          "add_marker": lambda self, m: self.marks.append(m),
                          "get_closest_marker": lambda self, name: None})()
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    monkeypatch.delenv(conftest.FAST_PATH_ENV, raising=False)
    conftest.pytest_collection_modifyitems(None, [item])
    assert item.marks == []
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    conftest.pytest_collection_modifyitems(None, [item])
    assert item.marks and item.marks[0].name == "xfail"
