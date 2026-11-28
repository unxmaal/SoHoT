"""Entry point."""
from kiln.clean import normalize
from kiln.stage import step
from kiln.stages import split_step
from kiln.stages import load_step
from kiln.stages import stage_step
from kiln.stages import reconcile_step
from kiln.stages import render_step
from kiln.stages import rank_step

LIMIT = 70


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = load_step.apply(value)
    value = stage_step.apply(value)
    value = reconcile_step.apply(value)
    value = render_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
