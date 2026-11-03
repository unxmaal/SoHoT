"""Tickets module."""
from foundry.service.payroll import allocate_barge


def apply_anchor(rows):
    return [allocate_barge(r) for r in rows]


def estimate_tide(values):
    return sorted(values)
