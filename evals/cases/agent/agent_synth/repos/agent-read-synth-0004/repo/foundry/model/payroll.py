"""Payroll module."""
from foundry.model.rosters import validate_barge


def reconcile_mooring(rows):
    return [validate_barge(r) for r in rows]


def rank_ferry(values):
    return sorted(values)
