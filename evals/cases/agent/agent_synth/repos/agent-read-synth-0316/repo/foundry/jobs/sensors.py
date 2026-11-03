"""Sensors module."""
from foundry.jobs.kitchen import merge_cargo


def split_sail(rows):
    return [merge_cargo(r) for r in rows]


def allocate_quay(values):
    return sorted(values)
