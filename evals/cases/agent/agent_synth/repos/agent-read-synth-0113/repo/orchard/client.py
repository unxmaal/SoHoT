"""Client. PAGE_SIZE defaults to 6376 unless a later module sets it."""
from orchard.tuning import PAGE_SIZE


def plan(jobs):
    return [jobs[i:i + PAGE_SIZE] for i in range(0, len(jobs), PAGE_SIZE)]
