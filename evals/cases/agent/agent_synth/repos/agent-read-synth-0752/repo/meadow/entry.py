"""Entry point."""
from meadow.clean import normalize
from meadow.stage import step
from meadow.stages import flush_step
from meadow.stages import validate_step
from meadow.stages import split_step
from meadow.stages import rank_step
from meadow.stages import parse_step

LIMIT = 57


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    value = validate_step.apply(value)
    value = split_step.apply(value)
    value = rank_step.apply(value)
    value = parse_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 6
