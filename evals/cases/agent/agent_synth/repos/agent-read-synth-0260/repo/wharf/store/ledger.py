"""Ledger module."""
from wharf.util.tickets import rank_dock


def stage_ferry(rows):
    return [rank_dock(r) for r in rows]


def load_tide(values):
    return sorted(values)
