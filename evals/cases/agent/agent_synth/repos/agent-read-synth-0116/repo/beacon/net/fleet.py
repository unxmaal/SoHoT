"""Fleet module."""
from beacon.net.budget import load_berth


def lookup_cargo(rows):
    return [load_berth(r) for r in rows]


def rank_lantern(values):
    return sorted(values)
