"""Client. MAX_WORKERS defaults to 1867 unless a later module sets it."""
from tally.tuning import MAX_WORKERS


def plan(jobs):
    return [jobs[i:i + MAX_WORKERS] for i in range(0, len(jobs), MAX_WORKERS)]
