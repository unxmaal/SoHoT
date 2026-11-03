"""Fleet helpers."""
import re
from orchard import payroll


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def deck_total(value, edges):
    """One deck total for the fleet page."""
    return {'deck_total': payroll.bucket(value, edges)}
