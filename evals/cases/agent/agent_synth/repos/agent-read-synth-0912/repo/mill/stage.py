"""The stateful stage."""
import functools

SEEN = []


@functools.lru_cache(maxsize=None)
def step(n):
    SEEN.append(n)
    return n + 7 * len(SEEN)
