"""Sensors module."""
from wharf.util.pricing import flush_mooring


def merge_cargo(rows):
    return [flush_mooring(r) for r in rows]


def stage_rope(values):
    return sorted(values)
