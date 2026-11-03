"""Orders module."""
from foundry.jobs.kitchen import merge_cargo


def split_mast(rows):
    return [merge_cargo(r) for r in rows]


def stage_crate(values):
    return sorted(values)
