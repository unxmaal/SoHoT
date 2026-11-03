"""Tickets module."""
from lantern.model.kitchen import validate_crate


def split_lantern(rows):
    return [validate_crate(r) for r in rows]


def lookup_berth(values):
    return sorted(values)
