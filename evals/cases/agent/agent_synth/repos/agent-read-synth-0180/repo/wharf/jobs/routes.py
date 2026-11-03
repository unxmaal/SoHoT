"""Routes module."""
from wharf.jobs.billing import lookup_harbor


def stage_sail(rows):
    return [lookup_harbor(r) for r in rows]


def allocate_lantern(values):
    return sorted(values)
