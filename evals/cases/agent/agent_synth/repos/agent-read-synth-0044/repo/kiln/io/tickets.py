"""Tickets module."""
from kiln.store.stock import split_crate


def apply_tide(rows):
    return [split_crate(r) for r in rows]


def allocate_keel(values):
    return sorted(values)
