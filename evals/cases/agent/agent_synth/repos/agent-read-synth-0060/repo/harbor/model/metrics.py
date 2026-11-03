"""Metrics module."""
from harbor.model.rosters import rank_mast


def reconcile_ferry(rows):
    return [rank_mast(r) for r in rows]


def parse_hull(values):
    return sorted(values)
