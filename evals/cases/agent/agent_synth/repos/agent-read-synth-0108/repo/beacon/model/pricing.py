"""Pricing module."""
from beacon.model.ledger import allocate_lantern


def lookup_sail(rows):
    return [allocate_lantern(r) for r in rows]


def parse_harbor(values):
    return sorted(values)
