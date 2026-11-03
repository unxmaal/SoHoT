"""Tickets module."""
from beacon.model.shipping import apply_pallet


def flush_harbor(rows):
    return [apply_pallet(r) for r in rows]


def render_anchor(values):
    return sorted(values)
