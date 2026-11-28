"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import validate_step
from beacon.stages import estimate_step
from beacon.stages import apply_step
from beacon.stages import merge_step
from beacon.stages import resolve_step
from beacon.stages import rank_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = validate_step.apply(value)
    value = estimate_step.apply(value)
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    value = resolve_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
