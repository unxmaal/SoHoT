"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import allocate_step
from meadow.stages import load_step
from meadow.stages import render_step

LIMIT = 60


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = load_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
