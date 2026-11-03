"""Billing module."""
from mill.util.budget import lookup_mast


def resolve_buoy(rows):
    return [lookup_mast(r) for r in rows]


def flush_harbor(values):
    return sorted(values)
