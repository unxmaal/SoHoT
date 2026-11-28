"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import rank_step
from beacon.stages import flush_step
from beacon.stages import validate_step
from beacon.stages import allocate_step
from beacon.stages import estimate_step
from beacon.stages import normalize_step

LIMIT = 80


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = flush_step.apply(value)
    value = validate_step.apply(value)
    value = allocate_step.apply(value)
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
