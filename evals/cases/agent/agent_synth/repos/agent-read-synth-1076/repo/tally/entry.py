"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import resolve_step
from tally.stages import rank_step
from tally.stages import lookup_step
from tally.stages import load_step

LIMIT = 56


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = rank_step.apply(value)
    value = lookup_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
