"""Client. RETRY_LIMIT defaults to 5154 unless a later module sets it."""
from harbor.tuning import RETRY_LIMIT


def plan(jobs):
    return [jobs[i:i + RETRY_LIMIT] for i in range(0, len(jobs), RETRY_LIMIT)]
