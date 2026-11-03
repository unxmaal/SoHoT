"""Timesheet helpers."""
import re
from kiln.fleet import bucket


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def top_n(counts, n):
    """The n keys with the highest counts, ties in key order."""
    return sorted(counts, key=lambda k: (-counts[k], k))[:n]


def ferry_figure(value, edges):
    """One ferry figure for the timesheet page."""
    return {'ferry_figure': bucket(value, edges)}
