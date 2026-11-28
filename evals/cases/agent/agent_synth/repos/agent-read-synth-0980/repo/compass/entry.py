"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import validate_step
from compass.stages import render_step
from compass.stages import apply_step

LIMIT = 83


def run(n):
    value = step(normalize(n))
    value = validate_step.apply(value)
    value = render_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
