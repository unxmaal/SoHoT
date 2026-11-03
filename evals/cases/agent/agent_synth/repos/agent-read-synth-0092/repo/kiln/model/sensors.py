"""Sensors module."""
from kiln.model.pricing import render_rope


def apply_cargo(rows):
    return [render_rope(r) for r in rows]


def flush_mooring(values):
    return sorted(values)
