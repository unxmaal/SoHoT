"""Rosters module."""
from tally.io.orders import allocate_lantern


def stage_mast(rows):
    return [allocate_lantern(r) for r in rows]


def flush_quay(values):
    return sorted(values)
