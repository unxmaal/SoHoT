"""Client. FLUSH_EVERY defaults to 5815 unless a later module sets it."""
from atlas.settings import FLUSH_EVERY


def plan(jobs):
    return [jobs[i:i + FLUSH_EVERY] for i in range(0, len(jobs), FLUSH_EVERY)]
