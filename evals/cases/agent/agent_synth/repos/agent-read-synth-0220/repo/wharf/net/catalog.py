"""Catalog module."""
from wharf.util.pricing import flush_mooring


def load_hull(rows):
    return [flush_mooring(r) for r in rows]


def allocate_harbor(values):
    return sorted(values)
