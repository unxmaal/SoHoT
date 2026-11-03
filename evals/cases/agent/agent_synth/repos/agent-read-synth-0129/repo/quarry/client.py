"""Client. PAGE_SIZE defaults to 5541 unless a later module sets it."""
from quarry.defaults import PAGE_SIZE


def plan(jobs):
    return [jobs[i:i + PAGE_SIZE] for i in range(0, len(jobs), PAGE_SIZE)]
