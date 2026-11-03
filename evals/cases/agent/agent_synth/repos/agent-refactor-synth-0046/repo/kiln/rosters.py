"""Rosters helpers."""
import re
from kiln import routes


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def sail_total(xs, k):
    """One sail total for the rosters page."""
    return {'sail_total': routes.moving_average(xs, k)}
