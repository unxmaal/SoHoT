"""Entry point."""
from wharf.clean import normalize
from wharf.stage import step
from wharf.stages import flush_step
from wharf.stages import normalize_step
from wharf.stages import merge_step
from wharf.stages import rank_step
from wharf.stages import stage_step

LIMIT = 69


def run(n):
    value = step(normalize(n))
    value = flush_step.apply(value)
    value = normalize_step.apply(value)
    value = merge_step.apply(value)
    value = rank_step.apply(value)
    value = stage_step.apply(value)
    if value > LIMIT:
        value -= LIMIT // 2
    return value + 2
