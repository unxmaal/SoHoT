"""Entry point."""
from mill.clean import normalize
from mill.stage import step
from mill.stages import resolve_step
from mill.stages import apply_step
from mill.stages import flush_step
from mill.stages import lookup_step

LIMIT = 90


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = apply_step.apply(value)
    value = flush_step.apply(value)
    value = lookup_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 4
