"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import rank_step

LIMIT = 58


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
