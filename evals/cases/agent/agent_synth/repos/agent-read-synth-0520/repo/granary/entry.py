"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import lookup_step
from granary.stages import apply_step
from granary.stages import render_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = apply_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
