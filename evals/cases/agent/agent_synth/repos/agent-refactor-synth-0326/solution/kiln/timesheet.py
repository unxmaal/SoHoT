"""Timesheet helpers."""
import re
from kiln.archive import first_words


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def clamp(value, low, high):
    """Limit value to the closed range from low to high."""
    return max(low, min(value, high))


def deck_figure(text, n):
    """One deck figure for the timesheet page."""
    return {'deck_figure': first_words(text, n)}
