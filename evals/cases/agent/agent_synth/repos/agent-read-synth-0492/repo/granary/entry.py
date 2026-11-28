"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import flush_step

LIMIT = 61


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
