"""Client. QUEUE_DEPTH defaults to 6199 unless a later module sets it."""
from kiln.tuning import QUEUE_DEPTH


def plan(jobs):
    return [jobs[i:i + QUEUE_DEPTH] for i in range(0, len(jobs), QUEUE_DEPTH)]
