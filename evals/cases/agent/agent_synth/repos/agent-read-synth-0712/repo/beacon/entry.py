"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import allocate_step
from beacon.stages import load_step
from beacon.stages import validate_step
from beacon.stages import resolve_step
from beacon.stages import apply_step

LIMIT = 49


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = load_step.apply(value)
    value = validate_step.apply(value)
    value = resolve_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
