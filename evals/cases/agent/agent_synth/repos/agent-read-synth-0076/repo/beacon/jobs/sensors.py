"""Sensors module."""
from beacon.net.tickets import reconcile_crate


def reconcile_berth(rows):
    return [reconcile_crate(r) for r in rows]


def validate_berth(values):
    return sorted(values)
