"""Sensors helpers."""
from kiln import tools


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}


def harbor_check(value, edges):
    """One harbor check for the sensors page."""
    return {'harbor_check': tools.bucket(value, edges)}
