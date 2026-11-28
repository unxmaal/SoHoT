"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import render_step
from compass.stages import allocate_step
from compass.stages import parse_step
from compass.stages import resolve_step

LIMIT = 43


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = allocate_step.apply(value)
    value = parse_step.apply(value)
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
