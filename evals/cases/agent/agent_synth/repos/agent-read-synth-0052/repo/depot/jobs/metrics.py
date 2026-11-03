"""Metrics module."""
from depot.store.archive import parse_berth


def parse_pallet(rows):
    return [parse_berth(r) for r in rows]


def apply_mast(values):
    return sorted(values)
