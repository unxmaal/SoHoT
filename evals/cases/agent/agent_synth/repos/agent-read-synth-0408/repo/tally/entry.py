"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import rank_step
from tally.stages import apply_step
from tally.stages import flush_step
from tally.stages import estimate_step
from tally.stages import split_step
from tally.stages import validate_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = apply_step.apply(value)
    value = flush_step.apply(value)
    value = estimate_step.apply(value)
    value = split_step.apply(value)
    value = validate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
