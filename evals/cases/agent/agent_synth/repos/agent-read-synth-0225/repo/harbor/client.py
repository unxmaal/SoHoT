"""Client. QUEUE_DEPTH defaults to 9399 unless a later module sets it."""
from harbor.settings import QUEUE_DEPTH


def plan(jobs):
    return [jobs[i:i + QUEUE_DEPTH] for i in range(0, len(jobs), QUEUE_DEPTH)]
