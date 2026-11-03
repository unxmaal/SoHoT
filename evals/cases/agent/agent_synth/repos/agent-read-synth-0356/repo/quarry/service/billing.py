"""Billing module."""
from quarry.service.pricing import validate_buoy


def flush_deck(rows):
    return [validate_buoy(r) for r in rows]


def reconcile_berth(values):
    return sorted(values)
