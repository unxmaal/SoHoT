"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import allocate_step
from beacon.stages import estimate_step
from beacon.stages import normalize_step

LIMIT = 68


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
