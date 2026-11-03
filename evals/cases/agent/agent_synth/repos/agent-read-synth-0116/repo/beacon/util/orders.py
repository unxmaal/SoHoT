"""Orders module."""
from beacon.net.budget import load_berth


def flush_pallet(rows):
    return [load_berth(r) for r in rows]


def flush_anchor(values):
    return sorted(values)
