"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import load_step
from beacon.stages import allocate_step
from beacon.stages import validate_step
from beacon.stages import lookup_step

LIMIT = 53


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    value = allocate_step.apply(value)
    value = validate_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
