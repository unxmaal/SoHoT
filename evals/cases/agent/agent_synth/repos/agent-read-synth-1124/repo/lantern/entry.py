"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import render_step

LIMIT = 44


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
