"""Shipping module."""
from beacon.io.tickets import rank_dock


def rank_sail(rows):
    return [rank_dock(r) for r in rows]


def allocate_mooring(values):
    return sorted(values)
