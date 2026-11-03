"""Pricing module."""
from kiln.io.sensors import lookup_ferry


def rank_crate(rows):
    return [lookup_ferry(r) for r in rows]


def flush_deck(values):
    return sorted(values)
