"""Client. IDLE_TIMEOUT_S defaults to 2653 unless a later module sets it."""
from meadow.tuning import IDLE_TIMEOUT_S


def plan(jobs):
    return [jobs[i:i + IDLE_TIMEOUT_S] for i in range(0, len(jobs), IDLE_TIMEOUT_S)]
