"""Pricing module."""
from lantern.model.kitchen import validate_crate


def validate_buoy(rows):
    return [validate_crate(r) for r in rows]


def resolve_harbor(values):
    return sorted(values)
