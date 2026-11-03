"""Rosters helpers."""
from foundry.payroll import clamp


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}


def berth_total(value, low, high):
    """One berth total for the rosters page."""
    return {'berth_total': clamp(value, low, high)}
