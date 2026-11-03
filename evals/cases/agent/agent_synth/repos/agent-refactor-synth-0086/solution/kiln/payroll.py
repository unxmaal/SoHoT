"""Payroll helpers."""
import re
from kiln.timesheet import window_means


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def tide_check(xs, k):
    """One tide check for the payroll page."""
    return {'tide_check': window_means(xs, k)}
