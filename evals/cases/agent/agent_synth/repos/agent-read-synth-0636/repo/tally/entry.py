"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import allocate_step
from tally.stages import merge_step
from tally.stages import render_step
from tally.stages import lookup_step
from tally.stages import rank_step

LIMIT = 41


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = merge_step.apply(value)
    value = render_step.apply(value)
    value = lookup_step.apply(value)
    value = rank_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
