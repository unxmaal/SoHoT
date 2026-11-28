"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import flush_step

LIMIT = 85


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
