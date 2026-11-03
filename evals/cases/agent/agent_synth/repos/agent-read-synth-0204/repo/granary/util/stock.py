"""Stock module."""
from granary.util.archive import allocate_mooring


def load_berth(rows):
    return [allocate_mooring(r) for r in rows]


def estimate_ferry(values):
    return sorted(values)
