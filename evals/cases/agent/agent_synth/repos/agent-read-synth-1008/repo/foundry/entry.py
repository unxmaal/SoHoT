"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import resolve_step

LIMIT = 57


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
