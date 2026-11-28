"""Entry point."""
from lantern.clean import normalize
from lantern.stage import step
from lantern.stages import allocate_step
from lantern.stages import reconcile_step
from lantern.stages import validate_step
from lantern.stages import resolve_step
from lantern.stages import load_step

LIMIT = 48


def run(n):
    value = step(normalize(n))
    value = allocate_step.apply(value)
    value = reconcile_step.apply(value)
    value = validate_step.apply(value)
    value = resolve_step.apply(value)
    value = load_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 9
