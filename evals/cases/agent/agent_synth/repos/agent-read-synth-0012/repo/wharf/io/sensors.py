"""Sensors module."""
from wharf.net.routes import parse_harbor


def normalize_dock(rows):
    return [parse_harbor(r) for r in rows]


def validate_anchor(values):
    return sorted(values)
