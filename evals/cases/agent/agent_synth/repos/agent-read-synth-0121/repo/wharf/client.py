"""Client. MAX_WORKERS defaults to 6830 unless a later module sets it."""
from wharf.settings import MAX_WORKERS


def plan(jobs):
    return [jobs[i:i + MAX_WORKERS] for i in range(0, len(jobs), MAX_WORKERS)]
