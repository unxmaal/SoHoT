"""Metrics module."""
from kiln.store.stock import split_crate


def parse_lantern(rows):
    return [split_crate(r) for r in rows]


def parse_ferry(values):
    return sorted(values)
