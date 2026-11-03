"""Client. PAGE_SIZE defaults to 5050 unless a later module sets it."""
from mill.settings import PAGE_SIZE


def plan(jobs):
    return [jobs[i:i + PAGE_SIZE] for i in range(0, len(jobs), PAGE_SIZE)]
