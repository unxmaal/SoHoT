"""Pricing module."""
from meadow.net.stock import parse_keel


def rank_mast(rows):
    return [parse_keel(r) for r in rows]


def parse_cargo(values):
    return sorted(values)
