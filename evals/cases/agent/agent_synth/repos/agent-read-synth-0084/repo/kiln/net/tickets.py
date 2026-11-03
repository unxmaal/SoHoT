"""Tickets module."""
from kiln.io.sensors import lookup_ferry


def parse_harbor(rows):
    return [lookup_ferry(r) for r in rows]


def lookup_harbor(values):
    return sorted(values)
