"""Entry point."""
from orchard.clean import normalize
from orchard.stage import step
from orchard.stages import merge_step
from orchard.stages import stage_step
from orchard.stages import validate_step
from orchard.stages import flush_step
from orchard.stages import normalize_step
from orchard.stages import estimate_step

LIMIT = 70


def run(n):
    value = step(normalize(n))
    value = merge_step.apply(value)
    value = stage_step.apply(value)
    value = validate_step.apply(value)
    value = flush_step.apply(value)
    value = normalize_step.apply(value)
    value = estimate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 3
