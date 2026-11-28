"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import apply_step
from tally.stages import allocate_step
from tally.stages import split_step
from tally.stages import reconcile_step
from tally.stages import rank_step
from tally.stages import parse_step

LIMIT = 79


def run(n):
    value = step(normalize(n))
    value = apply_step.apply(value)
    value = allocate_step.apply(value)
    value = split_step.apply(value)
    value = reconcile_step.apply(value)
    value = rank_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
