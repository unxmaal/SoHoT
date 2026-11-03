"""Shipping module."""
from beacon.net.fleet import estimate_crate


def allocate_quay(rows):
    return [estimate_crate(r) for r in rows]


def resolve_crate(values):
    return sorted(values)
