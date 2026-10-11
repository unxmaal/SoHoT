"""Knobs of the crowd that ranks discovered repos (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("crowd_limit", ["harness/neighbors.py:cohort(limit)"], [100, 250, 450], probe="crowd_limit",
       note="crowd size; read n= rather than the value, offline only cached people answer"),
    _k("half_life", ["harness/neighbors.py:HALF_LIFE_DAYS"], [90.0, 365.0, 1095.0, 1e9], probe="half_life",
       note="push-date decay; 1e9 is the decay switched off"),
    _k("hops", ["harness/neighbors.py:cohort(hops)"], [1, 2, 3], probe="hops",
       note="how far from the seeds the crowd reaches"),
    _k("min_degree", ["harness/neighbors.py:cohort(min_degree)"], [1, 2, 3, 5], probe="min_degree",
       note="how many of the crowd must follow someone for a second hop to reach them"),
    _k("min_shared", ["harness/neighbors.py:MIN_SHARED"], [1, 2, 3, 5, 8], probe="min_shared",
       note="how many of the crowd must star a repo for it to rank"),
    _k("per_repo", ["harness/neighbors.py:cohort(per_repo)"], [4, 8, 12, 24], probe="per_repo",
       note="contributors taken from each seed repo"),
    _k("population", ["harness/neighbors.py:POPULATION"], [1e5, 1e6, 5e6, 2e7, 1e8], probe="population",
       note="the world's star count, the denominator of enrichment"),
]
