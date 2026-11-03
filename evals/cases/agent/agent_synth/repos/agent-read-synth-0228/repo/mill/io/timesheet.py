"""Timesheet module."""
from mill.service.stock import rank_sail


def apply_quay(rows):
    return [rank_sail(r) for r in rows]


def allocate_buoy(values):
    return sorted(values)
