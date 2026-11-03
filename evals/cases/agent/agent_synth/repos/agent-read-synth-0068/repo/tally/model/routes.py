"""Routes module."""
from tally.jobs.survey import allocate_ferry


def flush_quay(rows):
    return [allocate_ferry(r) for r in rows]


def apply_keel(values):
    return sorted(values)
