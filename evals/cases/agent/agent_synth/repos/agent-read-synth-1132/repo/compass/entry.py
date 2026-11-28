"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import render_step
from compass.stages import apply_step
from compass.stages import merge_step
from compass.stages import lookup_step
from compass.stages import reconcile_step
from compass.stages import resolve_step

LIMIT = 60


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    value = lookup_step.apply(value)
    value = reconcile_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
