"""A sweep's fallback model is ranked on enough measured cases and a lower bound of its pass rate, so 3 of 6 cannot outrank 12 of 108 (#1179)."""
from harness import sweeps
from tests.test_knob_sweeps import DAY, NOW, record
from tests.test_sweep_floor_1009 import conn, serving  # noqa: F401


def runs_570_571(conn):
    """The 2026-10-23 repo shapes: served model 0 of 6 beside Qwopus 3 of 6 (run 570), Ornith 12 of 108 (run 571)."""
    record(conn, "code", 0, 6, limit="max_tokens.code>32768")
    record(conn, "code", 3, 6, spec="qwopus", at=NOW - DAY)
    record(conn, "code", 12, 108, spec="ornith", at=NOW - DAY, limit="max_tokens.code>32768")


def test_runs_570_and_571_sweep_the_108_case_model(conn, serving):
    runs_570_571(conn)
    got = sweeps.check(conn, now=NOW)
    p = got["planned"][0]
    assert p["spec"] == "ornith" and len(got["queued"]) == 1
    assert "best passing (12 of 108" in p["model"]


def test_two_runs_of_equal_size_still_pick_the_higher_rate(conn, serving):
    record(conn, "code", 0, 108, limit="max_tokens.code>32768")
    record(conn, "code", 12, 108, spec="ornith", at=NOW - DAY, limit="max_tokens.code>32768")
    record(conn, "code", 20, 108, spec="qwopus", at=NOW - DAY)
    assert sweeps.check(conn, now=NOW)["planned"][0]["spec"] == "qwopus"


def test_a_lower_bound_outranks_a_higher_rate_on_fewer_cases_over_the_floor(conn, serving):
    record(conn, "code", 0, 108, limit="max_tokens.code>32768")
    record(conn, "code", 5, 39, spec="ornith-think", at=NOW - DAY)
    record(conn, "code", 12, 108, spec="ornith", at=NOW - DAY, limit="max_tokens.code>32768")
    assert sweeps.check(conn, now=NOW)["planned"][0]["spec"] == "ornith"


def test_the_knob_decides_whether_six_cases_are_enough_to_rank_on(conn, serving, monkeypatch):
    runs_570_571(conn)
    monkeypatch.setattr(sweeps, "FALLBACK_MIN_CASES", 6)
    assert sweeps.plan(conn, now=NOW)[0]["spec"] == "qwopus"


def test_a_lane_with_only_small_runs_still_sweeps_its_best(conn, serving):
    record(conn, "code", 0, 6, limit="max_tokens.code>32768")
    record(conn, "code", 1, 6, spec="ornith", at=NOW - DAY)
    record(conn, "code", 3, 6, spec="qwopus", at=NOW - DAY)
    assert sweeps.plan(conn, now=NOW)[0]["spec"] == "qwopus"
