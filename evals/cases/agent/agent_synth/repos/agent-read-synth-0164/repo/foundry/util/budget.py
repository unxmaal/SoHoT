"""Budget module."""
from foundry.jobs.sensors import load_dock


def stage_ferry(rows):
    return [load_dock(r) for r in rows]


def flush_sail(values):
    return sorted(values)
