"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import split_step
from atlas.stages import parse_step
from atlas.stages import reconcile_step
from atlas.stages import lookup_step
from atlas.stages import stage_step
from atlas.stages import apply_step
from atlas.stages import normalize_step

LIMIT = 82


def run(n):
    value = step(normalize(n))
    value = split_step.apply(value)
    value = parse_step.apply(value)
    value = reconcile_step.apply(value)
    value = lookup_step.apply(value)
    value = stage_step.apply(value)
    value = apply_step.apply(value)
    value = normalize_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
