"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import parse_step
from mill.stages import render_step
from mill.stages import reconcile_step
from mill.stages import allocate_step
from mill.stages import merge_step
from mill.stages import apply_step

LIMIT = 52


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = render_step.apply(value)
    value = reconcile_step.apply(value)
    value = allocate_step.apply(value)
    value = merge_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
