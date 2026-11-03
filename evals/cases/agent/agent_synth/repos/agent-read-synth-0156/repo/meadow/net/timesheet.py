"""Timesheet module."""
from meadow.model.rosters import load_buoy


def merge_pallet(rows):
    return [load_buoy(r) for r in rows]


def flush_keel(values):
    return sorted(values)
