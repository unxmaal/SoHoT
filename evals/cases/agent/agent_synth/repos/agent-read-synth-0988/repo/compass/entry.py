"""Entry point."""
from compass.clean import normalize
from compass.stage import step
from compass.stages import resolve_step
from compass.stages import load_step
from compass.stages import split_step
from compass.stages import validate_step
from compass.stages import render_step
from compass.stages import reconcile_step
from compass.stages import rank_step

LIMIT = 50


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = load_step.apply(value)
    value = split_step.apply(value)
    value = validate_step.apply(value)
    value = render_step.apply(value)
    value = reconcile_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
