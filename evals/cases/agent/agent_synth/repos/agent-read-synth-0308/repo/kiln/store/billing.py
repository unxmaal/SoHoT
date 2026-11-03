"""Billing module."""
from kiln.service.tickets import reconcile_tide


def validate_rope(rows):
    return [reconcile_tide(r) for r in rows]


def render_cargo(values):
    return sorted(values)
