"""cases_needed at a per-lane effect of 0.05 searches to ~1600 cases; each n must not resum every binomial tail. #1292."""
from harness import power


def _counting(monkeypatch):
    seen = {"pmf": 0}
    real = power._pmf

    def counted(*a):
        seen["pmf"] += 1
        return real(*a)

    monkeypatch.setattr(power, "_pmf", counted)
    power.power_cells.cache_clear()
    power._tail.cache_clear()
    return seen


def test_a_small_effect_finds_its_holdout_without_resumming_each_tail(monkeypatch):
    seen = _counting(monkeypatch)
    assert power.cases_needed([0.5] * 136, 0.05, rho=1.0) == 1606
    # 115 million terms before #1292 (40 s on a Studio, 278 s in a CI make check).
    assert seen["pmf"] < 2_000_000


def test_power_cells_is_unchanged_by_sharing_the_tails(monkeypatch):
    _counting(monkeypatch)
    gain, lose = 0.2, 0.05
    want = 0.0
    for d in range(1, 41):
        need = power._critical(d, 0.05)
        if need <= d:
            want += power._pmf(40, d, gain + lose) * sum(
                power._pmf(d, j, gain / (gain + lose)) for j in range(need, d + 1))
    assert power.power_cells(gain, lose, 40, 0.05) == min(1.0, want)
