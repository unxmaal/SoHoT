"""Schema 75: the lane_probes table, which the DDL creates. #924."""
from __future__ import annotations

VERSION = 75


def indexes(conn) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS ix_lane_probes_lane ON lane_probes(lane, machine_id, at)")
