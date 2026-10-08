"""Schema 62: the knob_sweeps table, which the DDL creates. #636."""
from __future__ import annotations

VERSION = 62


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_knob_sweeps_key ON knob_sweeps(knob, lane, spec, machine_id)")
