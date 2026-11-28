"""Entry point."""
from foundry.clean import normalize
from foundry.stage import step
from foundry.stages import rank_step
from foundry.stages import validate_step
from foundry.stages import split_step
from foundry.stages import stage_step
from foundry.stages import lookup_step
from foundry.stages import load_step
from foundry.stages import merge_step

LIMIT = 42


def run(n):
    value = step(normalize(n))
    value = rank_step.apply(value)
    value = validate_step.apply(value)
    value = split_step.apply(value)
    value = stage_step.apply(value)
    value = lookup_step.apply(value)
    value = load_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
