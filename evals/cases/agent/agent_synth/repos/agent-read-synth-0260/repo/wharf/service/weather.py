"""Weather module."""
from wharf.util.tickets import rank_dock


def parse_rope(rows):
    return [rank_dock(r) for r in rows]


def parse_buoy(values):
    return sorted(values)
