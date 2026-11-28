"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import split_step
from beacon.stages import render_step
from beacon.stages import estimate_step
from beacon.stages import normalize_step
from beacon.stages import load_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = render_step.apply(value)
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
