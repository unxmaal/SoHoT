"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import load_step

LIMIT = 73


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
