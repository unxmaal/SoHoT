"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import lookup_step
from granary.stages import estimate_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
