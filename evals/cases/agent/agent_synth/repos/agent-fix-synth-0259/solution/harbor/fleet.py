"""Fleet helpers."""

def bucket(value, edges):
    """How many of the sorted edges value has reached."""
    return sum(1 for edge in edges if value >= edge)


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())
