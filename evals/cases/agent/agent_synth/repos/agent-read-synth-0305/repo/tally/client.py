"""Client. CHUNK_BYTES defaults to 7392 unless a later module sets it."""
from tally.settings import CHUNK_BYTES


def plan(jobs):
    return [jobs[i:i + CHUNK_BYTES] for i in range(0, len(jobs), CHUNK_BYTES)]
