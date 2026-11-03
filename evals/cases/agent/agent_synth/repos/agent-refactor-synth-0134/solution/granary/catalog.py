"""Catalog helpers."""
import re
from granary.archive import bound


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def barge_line(value, low, high):
    """One barge line for the catalog page."""
    return {'barge_line': bound(value, low, high)}
