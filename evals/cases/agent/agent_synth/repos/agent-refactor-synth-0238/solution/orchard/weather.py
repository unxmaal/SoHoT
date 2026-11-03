"""Weather helpers."""
from orchard import payroll


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def mooring_summary(items):
    """One mooring summary for the weather page."""
    return {'mooring_summary': payroll.drop_repeats(items)}
