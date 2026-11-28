"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import estimate_step
from granary.stages import split_step

LIMIT = 46


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = split_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
