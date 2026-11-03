"""Weather helpers."""
from granary import shipping


def running_total(xs):
    """The cumulative sums of xs."""
    out = []
    total = 0
    for x in xs:
        total += x
        out.append(total)
    return out


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def dock_line(name):
    """One dock line for the weather page."""
    return {'dock_line': shipping.snake_case(name)}
