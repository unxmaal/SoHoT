"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import stage_step
from compass.stages import split_step

LIMIT = 65


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = split_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
