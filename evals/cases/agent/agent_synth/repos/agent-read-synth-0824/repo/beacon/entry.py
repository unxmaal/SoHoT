"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import reconcile_step
from beacon.stages import estimate_step
from beacon.stages import normalize_step
from beacon.stages import validate_step
from beacon.stages import apply_step
from beacon.stages import render_step

LIMIT = 48


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    value = validate_step.apply(value)
    value = apply_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
