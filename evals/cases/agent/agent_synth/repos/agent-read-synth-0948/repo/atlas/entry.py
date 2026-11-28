"""Entry point."""
from atlas.clean import normalize
from atlas.stage import step
from atlas.stages import normalize_step
from atlas.stages import render_step
from atlas.stages import merge_step
from atlas.stages import estimate_step
from atlas.stages import parse_step
from atlas.stages import validate_step
from atlas.stages import reconcile_step

LIMIT = 79


def run(n):
    value = step(normalize(n))
    value = normalize_step.apply(value)
    value = render_step.apply(value)
    value = merge_step.apply(value)
    value = estimate_step.apply(value)
    value = parse_step.apply(value)
    value = validate_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 12
