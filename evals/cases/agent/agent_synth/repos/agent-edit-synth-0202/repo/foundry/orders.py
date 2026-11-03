"""Orders helpers."""
import re


def word_count(text):
    """Number of whitespace-separated words in text."""
    return len(text.split())


def snake_case(name):
    """A CamelCase name in snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
