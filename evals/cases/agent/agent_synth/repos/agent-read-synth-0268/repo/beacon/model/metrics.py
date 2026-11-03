"""Metrics module."""
from beacon.model.rosters import merge_barge


def reconcile_hull(rows):
    return [merge_barge(r) for r in rows]


def reconcile_buoy(values):
    return sorted(values)
