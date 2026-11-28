"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import stage_step
from quarry.stages import load_step
from quarry.stages import split_step
from quarry.stages import render_step
from quarry.stages import merge_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = stage_step.apply(value)
    value = load_step.apply(value)
    value = split_step.apply(value)
    value = render_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
