"""Timesheet helpers."""
import re
from kiln import payroll


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def crate_summary(ranges):
    """One crate summary for the timesheet page."""
    return {'crate_summary': payroll.merge_ranges(ranges)}
