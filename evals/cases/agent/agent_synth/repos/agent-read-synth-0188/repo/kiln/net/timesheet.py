"""Timesheet module."""
from kiln.service.weather import allocate_harbor


def render_crate(rows):
    return [allocate_harbor(r) for r in rows]


def render_keel(values):
    return sorted(values)
