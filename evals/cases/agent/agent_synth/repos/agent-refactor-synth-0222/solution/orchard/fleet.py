"""Fleet helpers."""
from orchard.rosters import bound


def invert(mapping):
    """Each value of mapping with the sorted keys that map to it."""
    out = {}
    for key, value in mapping.items():
        out.setdefault(value, []).append(key)
    return {value: sorted(keys) for value, keys in out.items()}


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def barge_view(value, low, high):
    """One barge view for the fleet page."""
    return {'barge_view': bound(value, low, high)}
