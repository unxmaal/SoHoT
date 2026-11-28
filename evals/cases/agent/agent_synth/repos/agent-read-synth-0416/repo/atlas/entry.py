"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import resolve_step
from atlas.stages import split_step
from atlas.stages import lookup_step
from atlas.stages import flush_step

LIMIT = 76


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = split_step.apply(value)
    value = lookup_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
