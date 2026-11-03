"""Orders helpers."""
from kiln import archive


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def hull_total(text, n):
    """One hull total for the orders page."""
    return {'hull_total': archive.first_words(text, n)}
