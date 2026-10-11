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


def test_the_old_names_rows_still_count_once_the_new_name_has_one_of_its_own(renamed, store_run):
    from harness import completion
    from harness import memory_store as ms
    store_run("20261002-000000-adopt-decide", "decide", specs={NEW: NEW},
              rows=[{"case_id": f"{renamed[0]}#1", "candidate": NEW, "passed": 1, "seconds": 2.0,
                     "peak_kb": 0, "detail": ""}], receipt={"max_tokens": completion.budget("decide")})
    conn = ms.connect()
    try:
        draws, _ = power.served_profile(conn, "decide", NEW)
    finally:
        conn.close()
    assert set(draws) == set(renamed)
    assert sum(len(v) for v in draws.values()) == 2 * len(renamed) + 1


def test_reading_the_served_profile_writes_nothing(renamed):
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        before = conn.total_changes
        power.served_profile(conn, "decide", NEW)
        assert conn.total_changes == before
    finally:
        conn.close()


def test_a_challenger_is_sized_against_the_renamed_incumbents_proposal(renamed):
    from harness import candidates
    from harness import memory_store as ms
    from harness.commands import measure as measure_cmd
    conn = ms.connect()
    try:
        for name, size in (("org/imajev", 4 * 1024 ** 3), ("org/ch", 8 * 1024 ** 3)):
            ms.record(conn, ms.Seen(name=name, source="t", lane="decide"))
            ms.set_size(conn, name, size)
        candidates.ensure(conn, OLD, proposal="org/imajev", lane="decide")
        candidates.ensure(conn, "ch", proposal="org/ch", lane="decide")
        conn.commit()
    finally:
        conn.close()
    _, plan = measure_cmd._plan(_ns(), "decide", NEW, "ch")
    assert plan.estimate["challenger_source"] == "size ratio"
    assert plan.estimate["challenger_s"] == pytest.approx(2 * plan.estimate["incumbent_s"])


def test_no_spelling_keyed_incumbent_lookup_is_left_to_reuse():
    assert not hasattr(power, "incumbent_profile")
    assert not hasattr(power, "incumbent_rates")


def test_soh_power_json_names_the_keys_the_profile_read(renamed, monkeypatch, capsys):
    import json

    from harness import screen, winners
    from harness.commands import adopt as adopt_cmd
    from harness.commands import common
    monkeypatch.setattr(winners, "typed", lambda: {"decide": NEW})
    monkeypatch.setattr(screen, "candidate_for", lambda lane, model, *a, **k: model)
    monkeypatch.setattr(common, "_JSON", True)
    adopt_cmd.cmd_power(argparse.Namespace(lane="decide", receipt=None, challenger="",
                                           power_budget_min=None, effect=None, json=True))
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["lanes"][0]["incumbent_keys"] == [OLD]
