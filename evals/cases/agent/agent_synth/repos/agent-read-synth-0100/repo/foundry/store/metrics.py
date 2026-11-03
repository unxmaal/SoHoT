"""Metrics module."""
from foundry.store.timesheet import validate_lantern


def lookup_buoy(rows):
    return [validate_lantern(r) for r in rows]


def load_harbor(values):
    return sorted(values)
