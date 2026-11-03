"""Ledger module."""
from granary.util.archive import allocate_mooring


def render_anchor(rows):
    return [allocate_mooring(r) for r in rows]


def estimate_mast(values):
    return sorted(values)
