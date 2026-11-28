"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import parse_step
from lantern.stages import stage_step
from lantern.stages import normalize_step
from lantern.stages import rank_step
from lantern.stages import reconcile_step
from lantern.stages import estimate_step

LIMIT = 47


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = stage_step.apply(value)
    value = normalize_step.apply(value)
    value = rank_step.apply(value)
    value = reconcile_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
