"""Interval estimates shared by every report that quotes a rate. #923, #918."""
from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k of n, rounded to 4 places."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, round(center - half, 4)), min(1.0, round(center + half, 4)))


def stratified(strata) -> tuple[float, float, float]:
    """95% (share, lo, hi) over (N, n, k) strata: weighted by N, variance with finite-population correction."""
    z = 1.96
    strata = [(N, n, k) for N, n, k in strata if N and n]
    total = sum(N for N, _, _ in strata)
    if not total:
        return (0.0, 0.0, 1.0)
    share = sum(N * k / n for N, n, k in strata) / total
    var = 0.0
    for N, n, k in strata:
        if n > 1 and n < N:
            # Wilson-centred p, so a sampled stratum at 0 of n still carries variance.
            p = (k + z * z / 2) / (n + z * z)
            var += (N / total) ** 2 * (1 - n / N) * p * (1 - p) / (n - 1)
    half = z * math.sqrt(var)
    return (round(share, 4), round(max(0.0, share - half), 4), round(min(1.0, share + half), 4))
