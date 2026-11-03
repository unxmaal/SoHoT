"""Rosters module."""
from wharf.model.survey import merge_crate


def resolve_quay(rows):
    return [merge_crate(r) for r in rows]


def allocate_dock(values):
    return sorted(values)
