"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import render_step
from beacon.stages import merge_step
from beacon.stages import flush_step
from beacon.stages import load_step

LIMIT = 55


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = merge_step.apply(value)
    value = flush_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
