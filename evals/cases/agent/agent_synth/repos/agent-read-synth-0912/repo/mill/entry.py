"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import flush_step

LIMIT = 76


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
