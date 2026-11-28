"""Entry point."""
from tally.clean import normalize
from tally.stage import step
from tally.stages import allocate_step
from tally.stages import apply_step
from tally.stages import merge_step
from tally.stages import stage_step
from tally.stages import load_step
from tally.stages import normalize_step
from tally.stages import flush_step

LIMIT = 44


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = apply_step.apply(value)
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    value = load_step.apply(value)
    value = normalize_step.apply(value)
    value = flush_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
