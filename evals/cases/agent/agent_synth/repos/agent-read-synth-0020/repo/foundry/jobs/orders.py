"""Orders module."""
from foundry.service.payroll import stage_pallet


def normalize_crate(rows):
    return [stage_pallet(r) for r in rows]


def reconcile_anchor(values):
    return sorted(values)
