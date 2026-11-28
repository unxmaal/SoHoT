"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import normalize_step
from beacon.stages import render_step
from beacon.stages import apply_step
from beacon.stages import reconcile_step
from beacon.stages import load_step
from beacon.stages import lookup_step

LIMIT = 61


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = render_step.apply(value)
    value = apply_step.apply(value)
    value = reconcile_step.apply(value)
    value = load_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
