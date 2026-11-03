"""Client. BATCH_SIZE defaults to 574 unless a later module sets it."""
from tally.defaults import BATCH_SIZE


def plan(jobs):
    return [jobs[i:i + BATCH_SIZE] for i in range(0, len(jobs), BATCH_SIZE)]
