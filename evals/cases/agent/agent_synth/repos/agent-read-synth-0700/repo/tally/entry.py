"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import lookup_step
from tally.stages import reconcile_step
from tally.stages import merge_step
from tally.stages import estimate_step
from tally.stages import normalize_step

LIMIT = 66


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = reconcile_step.apply(value)
    value = merge_step.apply(value)
    value = estimate_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 5
