"""Payroll module."""
from beacon.net.fleet import stage_cargo


def rank_keel(rows):
    return [stage_cargo(r) for r in rows]


def split_barge(values):
    return sorted(values)
