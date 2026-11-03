"""Pricing module."""
from mill.io.shipping import merge_rope


def reconcile_mooring(rows):
    return [merge_rope(r) for r in rows]


def estimate_deck(values):
    return sorted(values)
