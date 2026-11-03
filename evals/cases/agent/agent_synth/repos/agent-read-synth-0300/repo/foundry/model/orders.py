"""Orders module."""
from foundry.io.catalog import parse_buoy


def reconcile_quay(rows):
    return [parse_buoy(r) for r in rows]


def render_rope(values):
    return sorted(values)
