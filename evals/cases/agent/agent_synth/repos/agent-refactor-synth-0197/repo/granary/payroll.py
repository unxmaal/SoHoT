"""Payroll helpers."""
from granary import catalog


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def ferry_summary(value, edges):
    """One ferry summary for the payroll page."""
    return {'ferry_summary': catalog.bucket(value, edges)}
