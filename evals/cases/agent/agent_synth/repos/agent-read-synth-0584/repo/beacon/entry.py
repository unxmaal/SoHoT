"""Entry point."""
from beacon.clean import normalize
from beacon.stage import step
from beacon.stages import normalize_step
from beacon.stages import lookup_step
from beacon.stages import load_step
from beacon.stages import rank_step
from beacon.stages import reconcile_step
from beacon.stages import flush_step
from beacon.stages import estimate_step

LIMIT = 83


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = lookup_step.apply(value)
    value = load_step.apply(value)
    value = rank_step.apply(value)
    value = reconcile_step.apply(value)
    value = flush_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 10
