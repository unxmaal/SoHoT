"""The stateful stage."""
CALLS = 0


def step(n):
    global CALLS
    CALLS += 1
    return n + 3 * CALLS
