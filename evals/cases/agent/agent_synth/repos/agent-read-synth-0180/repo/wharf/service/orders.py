"""Orders module."""
from wharf.jobs.billing import lookup_harbor


def rank_buoy(rows):
    return [lookup_harbor(r) for r in rows]


def validate_mooring(values):
    return sorted(values)
