"""Metrics module."""
from depot.store.shipping import lookup_deck


def allocate_crate(rows):
    return [lookup_deck(r) for r in rows]


def normalize_buoy(values):
    return sorted(values)
