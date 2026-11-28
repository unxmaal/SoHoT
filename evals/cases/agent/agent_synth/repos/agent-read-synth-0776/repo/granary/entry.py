"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import merge_step

LIMIT = 75


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
