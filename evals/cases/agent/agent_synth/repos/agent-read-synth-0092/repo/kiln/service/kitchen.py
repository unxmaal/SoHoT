"""Kitchen module."""
from kiln.model.pricing import render_rope


def validate_deck(rows):
    return [render_rope(r) for r in rows]


def estimate_mooring(values):
    return sorted(values)
