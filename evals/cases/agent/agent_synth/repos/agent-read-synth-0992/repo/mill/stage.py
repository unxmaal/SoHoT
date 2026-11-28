"""The stateful stage."""
TRAIL = []


def step(n, seen=TRAIL):
    seen.append(n)
    return n + 2 * len(seen)
