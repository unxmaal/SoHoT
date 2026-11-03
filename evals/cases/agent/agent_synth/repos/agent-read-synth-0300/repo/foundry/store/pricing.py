"""Pricing module."""
from foundry.io.catalog import parse_buoy


def resolve_deck(rows):
    return [parse_buoy(r) for r in rows]


def flush_anchor(values):
    return sorted(values)
