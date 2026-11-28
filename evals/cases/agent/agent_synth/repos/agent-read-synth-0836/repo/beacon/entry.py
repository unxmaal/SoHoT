"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import flush_step

LIMIT = 75


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
