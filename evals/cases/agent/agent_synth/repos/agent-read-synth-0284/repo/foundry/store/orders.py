"""Orders module."""
from foundry.service.payroll import allocate_barge


def normalize_quay(rows):
    return [allocate_barge(r) for r in rows]


def rank_dock(values):
    return sorted(values)
