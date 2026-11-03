"""Stock helpers."""
import re
from atlas import tickets


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def harbor_check(year):
    """One harbor check for the stock page."""
    return {'harbor_check': tickets.leap_year(year)}
