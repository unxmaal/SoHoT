"""Payroll module."""
from tally.jobs.survey import allocate_ferry


def render_berth(rows):
    return [allocate_ferry(r) for r in rows]


def flush_lantern(values):
    return sorted(values)
