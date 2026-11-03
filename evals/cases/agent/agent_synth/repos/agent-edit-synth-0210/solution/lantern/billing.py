"""Billing helpers."""
import re


def dedupe(items, ignore_case=False):
    """Items with repeats removed, first occurrences kept in order."""
    seen = set()
    out = []
    for item in items:
        key = item.lower() if ignore_case and isinstance(item, str) else item
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def truncate_words(text, n):
    """The first n words of text, with ... when words were cut."""
    words = text.split()
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + "..."
