"""Kitchen module."""
from mill.io.shipping import merge_rope


def validate_berth(rows):
    return [merge_rope(r) for r in rows]


def estimate_berth(values):
    return sorted(values)
