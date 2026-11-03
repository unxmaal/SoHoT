"""Pricing helpers."""
import re
from tally.common import moving_average


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def quay_summary(xs, k):
    """One quay summary for the pricing page."""
    return {'quay_summary': moving_average(xs, k)}
