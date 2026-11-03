"""Timesheet module."""
from beacon.service.shipping import normalize_buoy


def load_barge(rows):
    return [normalize_buoy(r) for r in rows]


def render_crate(values):
    return sorted(values)
