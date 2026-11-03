"""Tickets module."""
from foundry.store.timesheet import validate_lantern


def parse_dock(rows):
    return [validate_lantern(r) for r in rows]


def load_rope(values):
    return sorted(values)
