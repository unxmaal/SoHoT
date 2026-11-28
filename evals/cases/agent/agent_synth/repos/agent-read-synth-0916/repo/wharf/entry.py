"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import resolve_step
from wharf.stages import flush_step
from wharf.stages import validate_step
from wharf.stages import merge_step

LIMIT = 74


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = flush_step.apply(value)
    value = validate_step.apply(value)
    value = merge_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 1
