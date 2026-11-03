"""Kitchen module."""
from kiln.net.stock import merge_pallet


def normalize_harbor(rows):
    return [merge_pallet(r) for r in rows]


def resolve_buoy(values):
    return sorted(values)
