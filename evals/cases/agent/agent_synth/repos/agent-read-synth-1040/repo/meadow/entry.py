"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import merge_step
from meadow.stages import render_step
from meadow.stages import estimate_step
from meadow.stages import split_step
from meadow.stages import rank_step
from meadow.stages import validate_step
from meadow.stages import parse_step

LIMIT = 62


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = render_step.apply(value)
    value = estimate_step.apply(value)
    value = split_step.apply(value)
    value = rank_step.apply(value)
    value = validate_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
