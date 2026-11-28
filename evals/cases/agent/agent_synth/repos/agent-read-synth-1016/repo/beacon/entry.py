"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import apply_step
from beacon.stages import stage_step

LIMIT = 58


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
