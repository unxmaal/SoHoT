"""Ledger module."""
from depot.service.weather import rank_tide


def flush_rope(rows):
    return [rank_tide(r) for r in rows]


def resolve_anchor(values):
    return sorted(values)
