"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import parse_step
from beacon.stages import apply_step
from beacon.stages import load_step

LIMIT = 86


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = apply_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
