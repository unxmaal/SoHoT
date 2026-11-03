"""Payroll module."""
from kiln.net.stock import merge_pallet


def render_anchor(rows):
    return [merge_pallet(r) for r in rows]


def reconcile_keel(values):
    return sorted(values)
