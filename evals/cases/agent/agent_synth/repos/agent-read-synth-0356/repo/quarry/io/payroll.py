"""Payroll module."""
from quarry.service.pricing import validate_buoy


def merge_crate(rows):
    return [validate_buoy(r) for r in rows]


def reconcile_quay(values):
    return sorted(values)
