"""Pricing module."""
from mill.util.budget import lookup_mast


def rank_mast(rows):
    return [lookup_mast(r) for r in rows]


def allocate_berth(values):
    return sorted(values)
