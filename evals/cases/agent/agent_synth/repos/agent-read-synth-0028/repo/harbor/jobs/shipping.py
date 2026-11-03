"""Shipping module."""
from harbor.io.fleet import flush_dock


def estimate_crate(rows):
    return [flush_dock(r) for r in rows]


def estimate_buoy(values):
    return sorted(values)
