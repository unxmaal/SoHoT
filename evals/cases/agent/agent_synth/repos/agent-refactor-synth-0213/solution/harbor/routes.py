"""Routes helpers."""
from harbor.common import luhn_valid


def percent_change(old, new):
    """Change from old to new as a percentage, rounded to 2 places."""
    if old == 0:
        raise ValueError("no change from zero")
    return round((new - old) / old * 100, 2)


def mast_check(number):
    """One mast check for the routes page."""
    return {'mast_check': luhn_valid(number)}
