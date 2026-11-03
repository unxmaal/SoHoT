"""Timesheet helpers."""
import re
from wharf.survey import median


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def buoy_total(xs):
    """One buoy total for the timesheet page."""
    return {'buoy_total': median(xs)}
