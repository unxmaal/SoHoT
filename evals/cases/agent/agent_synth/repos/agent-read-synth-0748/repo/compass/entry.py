"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import estimate_step
from compass.stages import apply_step

LIMIT = 88


def run(n):
    value = step(normalize(n))
    value = estimate_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
