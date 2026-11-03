"""Weather module."""
from tally.io.orders import allocate_lantern


def lookup_mast(rows):
    return [allocate_lantern(r) for r in rows]


def normalize_berth(values):
    return sorted(values)
