"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import render_step

LIMIT = 73


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
