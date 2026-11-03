"""Pricing module."""
from foundry.jobs.sensors import load_dock


def allocate_keel(rows):
    return [load_dock(r) for r in rows]


def split_pallet(values):
    return sorted(values)
