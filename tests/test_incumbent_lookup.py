"""measure and soh power read a renamed incumbent's rows by its candidates row, never a spelling. #740."""
import argparse

import pytest

from harness import gateway, power

MAC = gateway.REPO / "gateway" / "config.yaml"
OLD, NEW = "eval-imajev-4b", "imajev-4b-Q8_0"


@pytest.fixture
def renamed(store_run, monkeypatch):
    from harness import completion, holdout
    monkeypatch.setenv("GATEWAY_CONFIG", str(MAC))
    ids = holdout.for_lane("decide").holdout
    rows = [{"case_id": f"{c}#{k}", "candidate": OLD, "passed": int(i % 3 == 0) if k == 1 else 1,
             "seconds": 2.0, "peak_kb": 0, "detail": ""}
            for i, c in enumerate(ids) for k in (1, 2)]
    store_run("20261001-000000-adopt-decide", "decide", rows=rows, specs={OLD: OLD},
              receipt={"max_tokens": completion.budget("decide")})
    return ids


def _ns(**kw):
    base = {"repeat": None, "effect": 0.4, "power_budget_min": power.BUDGET_MIN}
    return argparse.Namespace(**{**base, **kw})


def test_measure_plans_from_the_rows_stored_under_the_incumbents_old_name(renamed, capsys):
    from harness.commands import measure as measure_cmd
    _, plan = measure_cmd._plan(_ns(), "decide", NEW)
    assert not plan.unmeasured
    assert plan.observed == 2 * len(renamed)
    assert plan.estimate["incumbent_source"] == "measured"
    assert "unmeasured" not in capsys.readouterr().out


def test_soh_power_profiles_the_incumbent_from_its_old_names_rows(renamed, monkeypatch):
    from harness import memory_store as ms
    from harness import screen, winners
    from harness.commands import adopt as adopt_cmd
    monkeypatch.setattr(winners, "typed", lambda: {"decide": NEW})
    monkeypatch.setattr(screen, "candidate_for", lambda lane, model, *a, **k: model)
    conn = ms.connect()
    try:
        _, spec, draws, median, _, _ = adopt_cmd._profile("decide", {}, conn)
    finally:
        conn.close()
    assert spec == NEW
    assert set(draws) == set(renamed)
    assert median == pytest.approx(2.0)


def test_a_plan_that_falls_back_to_unseen_says_so_on_the_run(store_run, capsys):
    from harness.commands import measure as measure_cmd
    _, plan = measure_cmd._plan(_ns(), "decide", NEW)
    assert plan.unmeasured
    out = capsys.readouterr().out
    assert f"assumes {power.UNSEEN:g}" in out


def test_soh_power_says_an_unseen_incumbent(store_run, monkeypatch, capsys):
    from harness import screen, winners
    from harness.commands import adopt as adopt_cmd
    monkeypatch.setattr(winners, "typed", lambda: {"decide": NEW})
    monkeypatch.setattr(screen, "candidate_for", lambda lane, model, *a, **k: model)
    adopt_cmd.cmd_power(argparse.Namespace(lane="decide", receipt=None, challenger="",
                                           power_budget_min=None, effect=None, json=False))
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "unmeasured" in text and f"assumes {power.UNSEEN:g}" in text
