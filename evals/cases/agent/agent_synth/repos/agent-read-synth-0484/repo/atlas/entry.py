"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import reconcile_step
from atlas.stages import estimate_step
from atlas.stages import apply_step
from atlas.stages import flush_step
from atlas.stages import lookup_step
from atlas.stages import rank_step
from atlas.stages import split_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = reconcile_step.apply(value)
    value = estimate_step.apply(value)
    value = apply_step.apply(value)
    value = flush_step.apply(value)
    value = lookup_step.apply(value)
    value = rank_step.apply(value)
    value = split_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
