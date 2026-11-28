"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import render_step
from meadow.stages import split_step
from meadow.stages import flush_step

LIMIT = 49


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = split_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
