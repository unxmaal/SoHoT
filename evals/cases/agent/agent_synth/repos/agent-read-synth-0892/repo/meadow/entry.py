"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import apply_step
from meadow.stages import merge_step
from meadow.stages import validate_step
from meadow.stages import stage_step
from meadow.stages import reconcile_step
from meadow.stages import lookup_step
from meadow.stages import render_step

LIMIT = 69


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    value = validate_step.apply(value)
    value = stage_step.apply(value)
    value = reconcile_step.apply(value)
    value = lookup_step.apply(value)
    value = render_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
