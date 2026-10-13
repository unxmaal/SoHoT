"""Schema 67: the watchdog_actions table, which the DDL creates. #814."""
from __future__ import annotations

VERSION = 67


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_watchdog_actions_key "
                 "ON watchdog_actions(criterion, subject, machine_id, at)")
