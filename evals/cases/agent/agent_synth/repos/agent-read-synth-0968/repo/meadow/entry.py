"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import load_step
from meadow.stages import stage_step

LIMIT = 81


def run(n):
    value = step(normalize(n))
    value = load_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
