"""Entry point."""
from depot.clean import normalize
from depot.stage import step
from depot.stages import allocate_step
from depot.stages import parse_step
from depot.stages import apply_step
from depot.stages import render_step
from depot.stages import reconcile_step

LIMIT = 80


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = parse_step.apply(value)
    value = apply_step.apply(value)
    value = render_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
