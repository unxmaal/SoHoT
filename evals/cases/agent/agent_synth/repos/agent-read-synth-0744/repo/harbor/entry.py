"""Entry point."""
from harbor.clean import normalize
from harbor.stage import step
from harbor.stages import resolve_step
from harbor.stages import split_step
from harbor.stages import parse_step
from harbor.stages import merge_step
from harbor.stages import reconcile_step

LIMIT = 73


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = split_step.apply(value)
    value = parse_step.apply(value)
    value = merge_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
