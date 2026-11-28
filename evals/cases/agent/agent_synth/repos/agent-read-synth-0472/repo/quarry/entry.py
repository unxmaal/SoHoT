"""Entry point."""
from quarry.clean import normalize
from quarry.stage import step
from quarry.stages import validate_step
from quarry.stages import load_step
from quarry.stages import reconcile_step

LIMIT = 72


def run(n):
    value = step(normalize(n))
    value = validate_step.apply(value)
    value = load_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 11
