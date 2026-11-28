"""Input cleanup."""


def normalize(n):
    return abs(n) % 13 + 26
