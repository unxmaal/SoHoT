"""Tickets module."""
from harbor.io.fleet import flush_dock


def stage_harbor(rows):
    return [flush_dock(r) for r in rows]


def load_dock(values):
    return sorted(values)
