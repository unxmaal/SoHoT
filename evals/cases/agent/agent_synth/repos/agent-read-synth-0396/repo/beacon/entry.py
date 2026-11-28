"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import parse_step
from beacon.stages import apply_step
from beacon.stages import rank_step
from beacon.stages import reconcile_step
from beacon.stages import flush_step
from beacon.stages import split_step
from beacon.stages import allocate_step

LIMIT = 40


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = apply_step.apply(value)
    value = rank_step.apply(value)
    value = reconcile_step.apply(value)
    value = flush_step.apply(value)
    value = split_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 7
