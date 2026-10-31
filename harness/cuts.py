"""A limit that binds records one limit_cuts row: the knob or backlog site, its value, what it cut and how much (#1087)."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time

from harness import paths

TABLE = "limit_cuts"
SPOOL = "limit_cuts.jsonl"
#: Seconds a cut written outside a caller's connection waits for the store's lock before it is spooled instead.
WRITE_WAIT_S = 0.25
_COLUMNS = ("at", "machine_id", "knob", "value", "what", "kept", "dropped")


def _machine_id(conn) -> int | None:
    """This machine's row, only when this process already resolved it: probing takes seconds."""
    from harness.memory_store import machines
    known = machines._THIS_MACHINE
    if known is None:
        return None
    try:
        row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?", (known["fingerprint"],)).fetchone()
    except Exception:  # noqa: BLE001 - a store without the row still takes the cut
        return None
    return int(row[0]) if row else None


def _spool_path():
    return paths.home() / SPOOL


def _spool(row: dict) -> bool:
    """Append a row to the spool; False when the home cannot be written, and then the cut is lost."""
    try:
        path = _spool_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        return False
    return True


def _spooled() -> list[dict]:
    """The spooled rows, taken: the file is renamed first, so a cut spooled meanwhile starts a new one."""
    path = _spool_path()
    if not path.exists():
        return []
    taken = path.with_name(f"{SPOOL}.{os.getpid()}.{time.time_ns()}")
    try:
        os.replace(path, taken)
        text = taken.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    with contextlib.suppress(OSError):
        taken.unlink()
    return out


def _insert(conn, rows: list[dict]) -> None:
    sql = f"INSERT INTO {TABLE} ({', '.join(_COLUMNS)}) VALUES ({', '.join('?' for _ in _COLUMNS)})"
    for r in rows:
        if r.get("machine_id") is None:
            r["machine_id"] = _machine_id(conn)
        conn.execute(sql, tuple(r.get(c) for c in _COLUMNS))


def _write(conn, rows: list[dict]) -> bool:
    """Insert into a connection; commit only what this call began. False when the store will not take them."""
    began = not getattr(conn, "in_transaction", True)
    try:
        _insert(conn, rows)
        if began:
            conn.commit()
    except Exception:  # noqa: BLE001 - a read-only, older or busy store: the rows are spooled
        with contextlib.suppress(Exception):
            if began:
                conn.rollback()
        return False
    return True


def _own_store():
    """A plain connection to this home's store when it exists and has the table; never creates or migrates one."""
    from harness import memory_store as ms, store
    if ms.lent() is not None or ms.migrating() is not None:
        return None
    if store.backend() == store.POSTGRES:
        return ms.connect()
    path = ms.db_path()
    if not path.exists():
        return None
    conn = sqlite3.connect(path, timeout=WRITE_WAIT_S)
    conn.execute(f"PRAGMA busy_timeout = {int(WRITE_WAIT_S * 1000)}")
    return conn


def flush(conn=None) -> int:
    """Move spooled cuts into the store; the number moved."""
    rows = _spooled()
    if not rows:
        return 0
    own = conn is None
    try:
        conn = _own_store() if own else conn
    except Exception:  # noqa: BLE001
        conn = None
    try:
        if conn is not None and _write(conn, rows):
            return len(rows)
    finally:
        if own and conn is not None:
            conn.close()
    for r in rows:
        _spool(r)
    return 0


def value_of(knob: str):
    """What a knob or site is set to now; None when it cannot be read here."""
    from harness import knobs
    try:
        return knobs.KNOBS[knob].default() if knob in knobs.KNOBS else knobs.resolve(knob)
    except Exception:  # noqa: BLE001 - a site another platform or a removed line holds
        return None


def cut(knob: str, what: str, *, value=None, kept: int | None = None, dropped: int | None = None,
        conn=None) -> None:
    """Record that `knob` (a registered knob, or a backlog site) cut `what`; its value now unless given; never raises."""
    from harness import memory_store as ms
    if ms.lent() is not None:
        return  # a read-only or dry run; spooled, the row would reach this home's store later. #1426.
    value = value_of(knob) if value is None else value
    try:
        number = float(value) if value is not None else None
    except (TypeError, ValueError):
        number = None
    row = {"at": time.time(), "machine_id": None, "knob": knob, "value": number, "what": str(what)[:500],
           "kept": kept, "dropped": dropped}
    if conn is not None and _write(conn, [row]):
        flush(conn)
        return
    _spool(row)
    flush()


def take(items, limit, knob: str, what: str, *, conn=None) -> list:
    """The first `limit` items; a cut is recorded when there were more. None is no limit."""
    items = list(items)
    if limit is None or len(items) <= limit:
        return items
    cut(knob, what, value=limit, kept=int(limit), dropped=len(items) - int(limit), conn=conn)
    return items[:int(limit)]


def filled(rows, limit, knob: str, what: str, *, conn=None):
    """`rows` as a LIMIT query returned them; a full page is recorded as a cut of unknown size."""
    rows = list(rows)
    if limit is not None and len(rows) >= limit:
        cut(knob, what, value=limit, kept=len(rows), conn=conn)
    return rows


def timed_out(exc: BaseException) -> bool:
    """Whether an exception is a timeout: subprocess, httpx, socket and urllib spell it differently."""
    if isinstance(exc, TimeoutError):
        return True
    if any("Timeout" in k.__name__ for k in type(exc).__mro__):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, BaseException) and timed_out(reason)


@contextlib.contextmanager
def timeout(knob: str, what: str, *, value=None, conn=None):
    """Record a cut when the block raises a timeout, then let it propagate."""
    try:
        yield
    except BaseException as exc:
        if timed_out(exc):
            cut(knob, what, value=value, kept=0, dropped=1, conn=conn)
        raise


def _grouped(conn, what: str, since: float, machines) -> dict:
    sql = f"SELECT knob, {what} FROM {TABLE} WHERE at >= ?"
    params: list = [since]
    if machines is not None:
        sql += f" AND (machine_id IS NULL OR machine_id IN ({', '.join('?' for _ in machines) or 'NULL'}))"
        params.extend(machines)
    try:
        return {r[0]: r[1] for r in conn.execute(sql + " GROUP BY knob", params)}
    except Exception:  # noqa: BLE001 - a store older than the table has no cuts
        return {}


def count(conn, since: float, machines=None) -> dict[str, int]:
    """Cuts recorded since `since`, by knob or site; machines None is every machine."""
    return {k: int(n) for k, n in _grouped(conn, "COUNT(*)", since, machines).items()}


def highest(conn, since: float, machines=None) -> dict:
    """The largest value each knob or site cut at since `since`."""
    return _grouped(conn, "MAX(value)", since, machines)
