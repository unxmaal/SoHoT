"""Routing policies scored offline over stored repo rows, with planted controls and the oracle as ceiling. #891."""
from __future__ import annotations

import json
import random

import pytest

from evals import repo_routing as R

#: P resolved; C applied, tests ran, wrong; B applied, pass_to_pass broken; I did not apply; E harness never ran.
CODES = {"P": (True, True, False, ""), "C": (False, True, False, "content_failed"),
         "B": (False, True, True, "content_failed"), "I": (False, False, False, "invalid_patch"),
         "E": (False, False, False, "environment_error")}


def _row(code, seconds=10.0):
    passed, applied, broken, fc = CODES[code]
    return {"passed": passed, "applied": applied, "p2p_broken": broken, "failure_class": fc, "seconds": seconds}


def _by(table: dict) -> dict:
    """table: case -> codes, one letter per route in the order local, cloud (and agentic between when 3)."""
    routes = ["local", "cloud"] if len(next(iter(table.values()))) == 2 else ["local", "agentic", "cloud"]
    return {r: {k: _row(codes[i]) for k, codes in table.items()} for i, r in enumerate(routes)}


def _random_table(rng, n, routes):
    return {f"t{i}-{rng.choice(('spec', 'symptom'))}": "".join(rng.choice("PCBI") for _ in range(routes))
            for i in range(n)}


def test_never_route_and_always_route_score_exactly_their_executors_resolve_rates():
    rng = random.Random(891)
    for routes in (2, 3):
        for _ in range(50):
            rep = R.report(_by(_random_table(rng, 30, routes)))
            ex, pol = rep["executors"], rep["policies"]
            assert pol["never-route"]["resolved"] == ex["local"]["resolved"]
            assert pol["always-route"]["resolved"] == ex["cloud"]["resolved"]
            assert pol["always-route"]["cloud_calls"] == rep["cases"] and pol["never-route"]["cloud_calls"] == 0
            if routes == 3:
                assert pol["agentic-only"]["resolved"] == ex["agentic"]["resolved"]


def test_no_policy_resolves_more_cases_than_the_oracle():
    rng = random.Random(892)
    for routes in (2, 3):
        for _ in range(50):
            pol = R.report(_by(_random_table(rng, 30, routes)))["policies"]
            top = pol["oracle"]["resolved"]
            assert all(p["resolved"] <= top for p in pol.values())
            assert pol["oracle"]["under_route"] == 0 and pol["oracle"]["over_route"] == 0


def test_the_gate_escalates_a_local_patch_that_does_not_apply_and_keeps_one_that_does():
    pol = R.report(_by({"a-spec": "IP", "b-spec": "PP", "c-spec": "BP"}))["policies"]
    assert (pol["gate-applies"]["resolved"], pol["gate-applies"]["cloud_calls"]) == (2, 1)
    assert (pol["gate-visible"]["resolved"], pol["gate-visible"]["cloud_calls"]) == (3, 2)
    assert pol["gate-visible"]["local_s"] == 30.0


def test_a_gate_passing_wrong_local_answer_counts_as_accepted_wrong_and_as_an_under_route_when_cloud_resolves():
    pol = R.report(_by({"a-spec": "CP", "b-spec": "CC"}))["policies"]
    g = pol["gate-visible"]
    assert (g["resolved"], g["accepted_wrong"], g["under_route"], g["cloud_calls"]) == (0, 2, 1, 0)
    a = R.report(_by({"a-spec": "PC"}))["policies"]["always-route"]
    assert (a["over_route"], a["under_route"]) == (1, 1)


def test_the_gate_never_rejects_a_resolved_row():
    rng = random.Random(893)
    for _ in range(50):
        rep = R.report(_by(_random_table(rng, 30, 3)))
        assert all(t["resolved_fail"] == 0 for gs in rep["gates"].values() for t in gs.values())


def test_a_case_the_harness_never_ran_on_any_route_is_left_out():
    rep = R.report(_by({"a-spec": "PE", "b-spec": "PP"}))
    assert rep["never_ran"] == ["a-spec"] and rep["cases"] == 1
    with pytest.raises(R.Refused, match="routing needs a local and a cloud run"):
        R.report({"local": {"a": _row("P")}})


def test_a_planted_dependency_bump_prompt_is_labelled_dependency_bump_and_a_fix_prompt_none():
    assert R.label("Bump httpx from 0.27 to 0.28 in uv.lock.") == "dependency_bump"
    assert R.label("Run ruff format over harness/.") == "formatter"
    assert R.label("Rename load_cases across the repo to read_cases.") == "codemod"
    assert R.label("soh repo-report crashes when a run has no receipt; pin the fix with a test.") == "none"
    rep = R.report(_by({"a-spec": "PP", "b-spec": "PP"}), {"a-spec": ("Bump httpx from 0.27 to 0.28", "spec")})
    assert rep["labels"] == {"dependency_bump": ["a-spec"], "none": ["b-spec"]}
    assert "unmeasured: dependency_bump: a-spec" in R.text(rep)


def test_spec_local_routes_by_the_variant_alone():
    meta = {"a-spec": ("", "spec"), "a-symptom": ("", "symptom")}
    p = R.report(_by({"a-spec": "PC", "a-symptom": "CP"}), meta)["policies"]["spec-local"]
    assert (p["resolved"], p["cloud_calls"], p["local_s"]) == (2, 1, 10.0)


def test_routing_reads_the_store_read_only_and_writes_nothing(store_run, tmp_path, capsys):
    import sqlite3

    from harness import cli
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "s.db")

    def rows(cand, codes):
        return [{"candidate": cand, "case_id": f"t{i}-spec", "passed": CODES[c][0], "failure_class": CODES[c][3],
                 "detail": "pass_to_pass broken: x" if CODES[c][2] else "", "seconds": 5.0,
                 "metrics": {"resolved": int(CODES[c][0]), "patch_applied": int(CODES[c][1])}}
                for i, c in enumerate(codes)]
    local = store_run("local", "repo", rows=rows("ornith", "PIBC"), conn=conn)
    cloud = store_run("cloud", "repo", rows=rows("opus", "PPPC"), conn=conn)
    conn.close()
    path = tmp_path / "s.db"
    before = path.read_bytes()
    assert cli.main(["repo-route", "--json", "--local", str(local), "--cloud", str(cloud), "--store", str(path),
                     "--cases", str(tmp_path)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert path.read_bytes() == before
    assert got["executors"] == {"local": {"resolved": 1, "n": 4}, "cloud": {"resolved": 3, "n": 4}}
    assert got["gates"]["local"]["visible"]["pass"] == 2 and got["policies"]["gate-visible"]["resolved"] == 3
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT count(*) FROM results").fetchone()[0] == 8
    assert cli.main(["repo-route", "--local", "999", "--cloud", str(cloud), "--store", str(path)]) == 1
