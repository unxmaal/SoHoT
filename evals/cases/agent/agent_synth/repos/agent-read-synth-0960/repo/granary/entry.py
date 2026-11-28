"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import estimate_step
from granary.stages import render_step

LIMIT = 79


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
