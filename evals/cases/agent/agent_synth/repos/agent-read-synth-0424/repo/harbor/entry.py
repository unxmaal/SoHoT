"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import rank_step
from harbor.stages import render_step

LIMIT = 59


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
