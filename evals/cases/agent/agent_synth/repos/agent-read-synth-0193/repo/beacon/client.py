"""Client. IDLE_TIMEOUT_S defaults to 6698 unless a later module sets it."""
from beacon.settings import IDLE_TIMEOUT_S


def plan(jobs):
    return [jobs[i:i + IDLE_TIMEOUT_S] for i in range(0, len(jobs), IDLE_TIMEOUT_S)]
