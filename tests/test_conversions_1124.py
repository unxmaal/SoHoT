"""A reply budget binds only through cuts that pass with more room, so its binding line counts those (#1124)."""
from harness import binding, convertible
from harness.commands import common
from tests.test_reply_budget_binding_1020 import DAY_AT, conn, runs_472_474  # noqa: F401


def test_the_binding_line_counts_cuts_that_converted_on_runs_472_and_474(conn):
    low, high = runs_472_474(conn)
    line = binding.render(binding.count(conn, now=DAY_AT))
    assert "max_tokens.repo at 32768: 0 of 21 cuts converted" in line and f"run {high}'s ladder" in line
    assert "hit it" in line


def test_a_dry_run_over_runs_472_and_474_reproduces_0_of_21(conn, tmp_path, capsys):
    low, high = runs_472_474(conn)
    conn.commit()
    a = common.parsed("climb", "repo", "ornith", "--runs", f"{low},{high}", "--store", str(tmp_path / "d.db"))
    assert a.func(a) == 0
    assert "0 of 21 cuts at 32768 converted" in capsys.readouterr().out


def test_among_equally_confounded_pairings_the_one_with_the_most_cuts_decides(conn):
    from tests.test_reply_budget_binding_1020 import LOW_SAMPLING, VENDOR, VENDOR_SPEC, record
    cases = [f"c{i}" for i in range(30)]
    record(conn, "ornith", {c: "cut" for c in cases[:21]}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 9000)
    record(conn, "ornith", {c: "cut" for c in cases[:5]}, top=32768, sampling=LOW_SAMPLING, at=DAY_AT - 100)
    record(conn, VENDOR_SPEC, {c: "wrong" for c in cases}, top=65536, sampling=VENDOR, at=DAY_AT - 5000)
    got = convertible.best(convertible.stored(conn, "repo", "ornith", None), "ornith", 32768)
    assert (got["passed"], got["cut"]) == (0, 21)
