"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import normalize_step

LIMIT = 77


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
