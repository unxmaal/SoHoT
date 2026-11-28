"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import estimate_step

LIMIT = 52


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
