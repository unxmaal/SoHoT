"""Tickets module."""
from meadow.net.stock import parse_keel


def normalize_crate(rows):
    return [parse_keel(r) for r in rows]


def merge_quay(values):
    return sorted(values)
