"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import render_step
from meadow.stages import merge_step
from meadow.stages import resolve_step
from meadow.stages import allocate_step
from meadow.stages import reconcile_step
from meadow.stages import stage_step

LIMIT = 58


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = merge_step.apply(value)
    value = resolve_step.apply(value)
    value = allocate_step.apply(value)
    value = reconcile_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
