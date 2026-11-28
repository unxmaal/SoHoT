"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import flush_step

LIMIT = 89


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
