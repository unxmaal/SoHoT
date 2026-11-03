"""Billing module."""
from meadow.store.tickets import reconcile_sail


def flush_cargo(rows):
    return [reconcile_sail(r) for r in rows]


def validate_crate(values):
    return sorted(values)
