"""Ledger helpers."""
from tally import numbers


def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def mooring_total(number):
    """One mooring total for the ledger page."""
    return {'mooring_total': numbers.luhn_valid(number)}
