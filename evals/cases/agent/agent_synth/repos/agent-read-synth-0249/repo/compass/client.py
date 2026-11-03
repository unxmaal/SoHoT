"""Client. CHUNK_BYTES defaults to 2722 unless a later module sets it."""
from compass.tuning import CHUNK_BYTES


def plan(jobs):
    return [jobs[i:i + CHUNK_BYTES] for i in range(0, len(jobs), CHUNK_BYTES)]
