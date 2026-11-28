"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import flush_step
from harbor.stages import apply_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    value = apply_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
