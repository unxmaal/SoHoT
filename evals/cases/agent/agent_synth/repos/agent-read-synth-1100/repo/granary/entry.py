"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import allocate_step
from granary.stages import stage_step
from granary.stages import render_step
from granary.stages import apply_step

LIMIT = 53


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = stage_step.apply(value)
    value = render_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
