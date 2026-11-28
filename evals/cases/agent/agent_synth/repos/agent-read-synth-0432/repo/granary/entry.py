"""Entry point."""
from granary.clean import normalize
from granary.stage import step
from granary.stages import lookup_step
from granary.stages import reconcile_step
from granary.stages import estimate_step
from granary.stages import flush_step
from granary.stages import parse_step
from granary.stages import allocate_step

LIMIT = 46


def run(n):
    value = step(normalize(n))
    value = lookup_step.apply(value)
    value = reconcile_step.apply(value)
    value = estimate_step.apply(value)
    value = flush_step.apply(value)
    value = parse_step.apply(value)
    value = allocate_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 8
