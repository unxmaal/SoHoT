"""Payroll helpers."""
import re


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def luhn_valid(number):
    """True when the digits of number pass the Luhn checksum."""
    digits = [int(d) for d in number if d.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return bool(digits) and total % 10 == 0
