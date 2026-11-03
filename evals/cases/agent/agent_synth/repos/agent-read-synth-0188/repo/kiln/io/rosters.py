"""Rosters module."""
from kiln.service.weather import allocate_harbor


def load_tide(rows):
    return [allocate_harbor(r) for r in rows]


def reconcile_sail(values):
    return sorted(values)
