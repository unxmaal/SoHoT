"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import parse_step
from mill.stages import load_step
from mill.stages import flush_step
from mill.stages import allocate_step
from mill.stages import reconcile_step

LIMIT = 86


def run(n):
    value = step(normalize(n))
    value = parse_step.apply(value)
    value = load_step.apply(value)
    value = flush_step.apply(value)
    value = allocate_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
