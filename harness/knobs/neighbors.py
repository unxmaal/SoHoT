"""Knobs of the crowd that ranks discovered repos (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("crowd_limit", ["harness/neighbors.py:cohort(limit)"], [100, 250, 450], probe="crowd_limit",
       note="crowd size; read n= rather than the value, offline only cached people answer"),
    _k("crowd_star_pages", ["harness/neighbors.py:STAR_PAGES"], [1, 2, 3, 5, 10], probe="star_pages", unit="pages",
       note="pages of 100 stars read per crowd member, newest first; on the 250-person crowd 2026-10-25 they read "
            "13/22/29/40/59% of its 128k stars for 250/382/484/637/887 cold starred requests, inside the sweep's "
            "900-request --budget beside ~445 repo lookups only at 1 page (#764)"),
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

NEVER_CUTS = {
    "harness/neighbors.py:HALF_LIFE_DAYS": "push-date decay on a repo's score; it reorders the ranking and drops no repo",
    "harness/neighbors.py:POPULATION": "the denominator of a repo's enrichment; it weights the score and drops no repo",
}
