"""Payroll helpers."""
import re


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?=[A-Z])", "_", name).lower()
