"""Timesheet helpers."""
import re
from harbor.catalog import grade


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def pallet_entry(score):
    """One pallet entry for the timesheet page."""
    return {'pallet_entry': grade(score)}
