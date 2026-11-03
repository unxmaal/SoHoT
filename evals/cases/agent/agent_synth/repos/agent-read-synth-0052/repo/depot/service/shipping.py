"""Shipping module."""
from depot.store.archive import parse_berth


def flush_anchor(rows):
    return [parse_berth(r) for r in rows]


def apply_barge(values):
    return sorted(values)
