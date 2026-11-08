"""The store's Postgres container on this machine: its secrets, its roles, and the home's switch to it. #1507."""
from __future__ import annotations

import json
import os
import secrets as _secrets
import subprocess
import sys
from pathlib import Path

from harness import paths, store

COMPOSE = paths.REPO / "deploy" / "postgres" / "compose.yaml"
CONTAINER = "sohot-postgres"
OWNER = "discovery"
#: The loopback port compose publishes; store.json names it so every process finds it.
PORT = 5433
#: How long `docker compose up --wait` may take before the service counts as not up.
UP_TIMEOUT_S = 180


class Keychain:
    """One login Keychain item of service sohot-postgres, account the role."""

    def __init__(self, account: str, run=subprocess.run):
        self.account, self.run = account, run

    def get(self) -> str:
        from harness.nodes import keychain
        return keychain(store.SECRET_SERVICE, self.account)

    def set(self, value: str) -> None:
        # `security -i` reads its command from stdin, so the password is never in argv.
        r = self.run(["security", "-i"], capture_output=True, text=True,
                     input=f"add-generic-password -U -a {self.account} -s {store.SECRET_SERVICE} -w {value}\n")
        if r.returncode != 0:
            raise RuntimeError(f"could not store the {self.account} password: {r.stderr.strip()}")


def secret_store(account: str, platform: str | None = None):
    """The Keychain on a Mac, else a 0600 file under the home."""
    from harness import gateway_key
    if (platform or sys.platform) == "darwin" and os.environ.get(gateway_key.STORE_ENV) != "file":
        return Keychain(account)
    return gateway_key.FileStore(paths.home() / f"postgres-{account}.secret")


def password(account: str, *, ensure: bool = False, secret=None) -> str:
    """A role's password; with ensure, generated and stored first when there is none."""
    secret = secret or secret_store(account)
    got = secret.get()
    if not got and ensure:
        got = _secrets.token_urlsafe(32)
        secret.set(got)
    return got


def compose(action: list[str], *, run=subprocess.run, environ=None, secret=None) -> subprocess.CompletedProcess:
    """`docker compose` on the store's compose file, the owner password passed in the environment only."""
    env = dict(os.environ if environ is None else environ)
    env["SOHOT_PG_PASSWORD"] = password(OWNER, ensure=True, secret=secret)
    env.setdefault("SOHOT_PG_PORT", str(PORT))
    from harness import cuts
    with cuts.timeout("harness/store_service.py:UP_TIMEOUT_S", "docker compose " + " ".join(action)):
        return run(["docker", "compose", "-f", str(COMPOSE), *action], env=env,
                   capture_output=True, text=True, timeout=UP_TIMEOUT_S)


def owner_environ(port: int = PORT, secret=None) -> dict:
    """PG* variables reaching the container as its owner."""
    return {"PGHOST": "127.0.0.1", "PGPORT": str(port), "PGDATABASE": OWNER, "PGUSER": OWNER,
            "PGPASSWORD": password(OWNER, secret=secret)}


def grant_reader(conn, role: str, pw: str) -> None:
    """The read-only role: it may connect and SELECT, today's tables and every later one, and nothing else."""
    from psycopg import sql
    raw = conn._conn
    exists = raw.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    raw.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE")
                .format(sql.Identifier(role), sql.Literal(pw)))
    raw.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(role)))
    schema = raw.execute("SELECT current_schema()").fetchone()[0]
    db = raw.execute("SELECT current_database()").fetchone()[0]
    ident = {"role": sql.Identifier(role), "schema": sql.Identifier(schema), "db": sql.Identifier(db)}
    for stmt in ("GRANT CONNECT ON DATABASE {db} TO {role}",
                 "GRANT USAGE ON SCHEMA {schema} TO {role}",
                 "GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}",
                 "ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {role}"):
        raw.execute(sql.SQL(stmt).format(**ident))
    raw.commit()


#: How long a dump or restore of the store may take inside the container.
DUMP_TIMEOUT_S = 1800


#: Drops every table of the store's schema, so one a later migration added does not outlive a restore. #1610.
DROP_TABLES = ("DO $$DECLARE t record; BEGIN FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
               "LOOP EXECUTE format('DROP TABLE IF EXISTS %I.%I CASCADE', current_schema(), t.tablename); END LOOP; END$$")


def in_container(argv: list, stdin: bool = False) -> list:
    """argv run inside the store's container, whose tools reach the store on its local socket."""
    return ["docker", "exec", *(["-i"] if stdin else []), CONTAINER, *argv]


def _failed(what: str, got) -> RuntimeError:
    err = got.stderr or b""
    return RuntimeError(f"{what} exited {got.returncode}: "
                        f"{(err.decode(errors='replace') if isinstance(err, bytes) else err).strip()}")


def dump(dest: Path, *, run=subprocess.run) -> Path:
    """pg_dump -Fc of the store from inside its container (local socket, no password), into `dest`."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    from harness import cuts
    with open(tmp, "wb") as out, cuts.timeout("harness/store_service.py:DUMP_TIMEOUT_S", "pg_dump of the store"):
        got = run(in_container(["pg_dump", "-U", OWNER, "-Fc", OWNER]),
                  stdout=out, stderr=subprocess.PIPE, timeout=DUMP_TIMEOUT_S)
    if got.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise _failed("pg_dump", got)
    os.replace(tmp, dest)
    return dest


def restore(src: Path, *, run=subprocess.run) -> None:
    """Replace the store with a pg_dump -Fc file in one transaction, tables it lacks dropped; a failure changes nothing."""
    from harness import cuts
    src = Path(src)
    sql = src.with_name(src.name + ".restore.sql")
    try:
        with open(src, "rb") as data, open(sql, "wb") as out, \
                cuts.timeout("harness/store_service.py:DUMP_TIMEOUT_S", "pg_restore of the store"):
            got = run(in_container(["pg_restore", "--clean", "--if-exists", "--no-owner", "-f", "-"], stdin=True),
                      stdin=data, stdout=out, stderr=subprocess.PIPE, timeout=DUMP_TIMEOUT_S)
        if got.returncode != 0:
            raise _failed("pg_restore", got)
        with open(sql, "rb") as data, cuts.timeout("harness/store_service.py:DUMP_TIMEOUT_S", "restore of the store"):
            got = run(in_container(["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-1", "-U", OWNER, "-d", OWNER,
                                    "-c", DROP_TABLES, "-f", "-"], stdin=True),
                      stdin=data, capture_output=True, timeout=DUMP_TIMEOUT_S)
        if got.returncode != 0:
            raise _failed("psql restore", got)
    finally:
        sql.unlink(missing_ok=True)


def schema(*, run=subprocess.run) -> int:
    """The store's meta schema through the container's psql, so a caller with no psycopg (deploy_switch) can read it."""
    from harness import cuts
    with cuts.timeout("harness/store_service.py:DUMP_TIMEOUT_S", "schema read of the store"):
        got = run(in_container(["psql", "-X", "-tA", "-U", OWNER, "-d", OWNER,
                                "-c", "SELECT value FROM meta WHERE key = 'schema'"]),
                  capture_output=True, text=True, timeout=DUMP_TIMEOUT_S)
    if got.returncode != 0:
        raise _failed("psql schema read", got)
    out = (got.stdout or "").strip()
    return int(out) if out else 0


def marker_for(port: int = PORT, reader: str = store.DEFAULT_READER) -> dict:
    return {"backend": store.POSTGRES, "host": "127.0.0.1", "port": port, "dbname": OWNER,
            "user": OWNER, "reader": reader}


def switch(to: str, home: Path | None = None, *, port: int = PORT, dry_run: bool = False) -> dict:
    """Point this home at Postgres (write store.json) or back at SQLite (set it aside as store.json.off)."""
    home = Path(home) if home is not None else paths.home()
    on, off = home / store.MARKER, home / (store.MARKER + ".off")
    if to == store.POSTGRES:
        body = marker_for(port)
        if not dry_run:
            tmp = on.with_name(on.name + ".tmp")
            tmp.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, on)
        return {"ok": True, "backend": store.POSTGRES, "wrote": str(on), "marker": body, "dry_run": dry_run}
    if not dry_run and on.exists():
        os.replace(on, off)
    return {"ok": True, "backend": store.SQLITE, "set_aside": str(off), "dry_run": dry_run}
