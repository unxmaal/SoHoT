"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import validate_step
from lantern.stages import stage_step

LIMIT = 87


def run(n):
    value = step(normalize(n))
    value = validate_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
