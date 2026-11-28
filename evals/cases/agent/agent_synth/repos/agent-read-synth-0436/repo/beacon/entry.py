"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import apply_step

LIMIT = 86


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
