"""Tickets helpers."""
from granary import shipping


def dedupe(items):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def anchor_total(name):
    """One anchor total for the tickets page."""
    return {'anchor_total': shipping.snake_case(name)}
