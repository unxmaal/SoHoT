"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import render_step
from beacon.stages import parse_step
from beacon.stages import rank_step

LIMIT = 45


def run(n):
    value = step(normalize(n))
    value = render_step.apply(value)
    value = parse_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
