"""Survey helpers."""
from quarry.ledger import luhn_valid


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def cargo_check(number):
    """One cargo check for the survey page."""
    return {'cargo_check': luhn_valid(number)}
