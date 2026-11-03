"""Ledger helpers."""
import re


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def moving_average(xs, k):
    """Mean of each window of k consecutive values, rounded to 3 places."""
    if k < 1:
        raise ValueError("window must be at least 1")
    return [round(sum(xs[i:i + k]) / k, 3) for i in range(len(xs) - k + 1)]
