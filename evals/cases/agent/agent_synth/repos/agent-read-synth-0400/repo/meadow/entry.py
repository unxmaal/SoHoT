"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import resolve_step
from meadow.stages import split_step
from meadow.stages import normalize_step
from meadow.stages import rank_step
from meadow.stages import parse_step
from meadow.stages import reconcile_step

LIMIT = 44


def run(n):
    value = step(normalize(n))
    value = resolve_step.apply(value)
    value = split_step.apply(value)
    value = normalize_step.apply(value)
    value = rank_step.apply(value)
    value = parse_step.apply(value)
    value = reconcile_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
