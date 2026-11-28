"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import normalize_step
from beacon.stages import stage_step
from beacon.stages import load_step
from beacon.stages import rank_step

LIMIT = 80


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = stage_step.apply(value)
    value = load_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
