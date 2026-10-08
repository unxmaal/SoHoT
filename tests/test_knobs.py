"""The knob registry: every outcome-gating constant declares its range, lanes and binding signal (#636)."""
import json
from pathlib import Path

import pytest

from harness import knobs, lanes, probes, reasons

REPO = Path(__file__).resolve().parent.parent
BACKLOG_FILE = REPO / "tests" / "gauntlet" / "knob_backlog.json"


def _backlog():
    return json.loads(BACKLOG_FILE.read_text(encoding="utf-8"))


def test_the_inventory_finds_each_shape_of_gating_constant():
    src = ("GIB = 1024 ** 3\n"
           "TIMEOUT_S = 180.0\n"
           "MEMORY_CEILING = 22 * GIB\n"
           "BUDGET = {'code': 32768, 'svg': MAX_TOKENS}\n"
           "_MIN_INK: float = 0.01\n"
           "RUNAWAY_MIN_WORDS = -6\n")
    assert knobs.gating(src, "harness/m.py") == [
        "harness/m.py:TIMEOUT_S", "harness/m.py:MEMORY_CEILING", "harness/m.py:BUDGET",
        "harness/m.py:_MIN_INK", "harness/m.py:RUNAWAY_MIN_WORDS"]


def test_the_inventory_is_quiet_on_constants_that_gate_nothing_and_fires_once_one_joins():
    innocent = ("SCHEMA_VERSION = 3\n"
                "GIB = 1024 ** 3\n"
                "MAX_NAME = 'svg'\n"
                "MAX_LANES = ('svg', 'web')\n"
                "MAX_ON = True\n"
                "max_tokens = 4000\n"
                "def f():\n    MAX_TOKENS = 4000\n    return MAX_TOKENS\n"
                "class C:\n    TIMEOUT_S = 3\n")
    assert knobs.gating(innocent, "harness/m.py") == []
    assert knobs.gating(innocent + "MAX_TOKENS = 4000\n", "harness/m.py") == ["harness/m.py:MAX_TOKENS"]


def test_the_inventory_reads_only_production_python():
    found = knobs.inventory(REPO)
    assert found and all(s.startswith(("harness/", "evals/")) for s in found)
    assert not any(s.startswith("evals/cases/") for s in found)
    assert "harness/completion.py:BUDGET" in found


def test_every_knob_names_a_value_that_exists():
    for k in knobs.KNOBS.values():
        for site in k.sites:
            assert knobs.resolve(site) is not None, site


def test_every_knob_s_range_holds_its_default_for_every_lane_it_affects():
    for k in knobs.KNOBS.values():
        for lane in k.lanes or ("",):
            assert k.default(lane) in k.values, (k.name, lane, k.default(lane))


def test_every_knob_s_lanes_are_lanes():
    for k in knobs.KNOBS.values():
        assert set(k.lanes) <= set(lanes.ALL), k.name


def test_a_knob_that_gates_an_eval_names_the_limit_that_shows_it_binding():
    for k in knobs.KNOBS.values():
        if k.probe:
            continue
        assert k.limit, f"{k.name} declares no binding signal"


def test_the_knobs_that_have_bitten_are_registered():
    sites = {s for k in knobs.KNOBS.values() for s in k.sites}
    assert {"harness/completion.py:BUDGET", "harness/completion.py:MAX_TOKENS",
            "harness/completion.py:TIMEOUT_S", "harness/completion.py:LOAD_TIMEOUT_S",
            "harness/inspect.py:MEMORY_CEILING", "harness/audio.py:SECONDS_PER_WORD_CEILING"} <= sites


def test_a_lane_scoped_limit_is_named_per_lane():
    budget = knobs.KNOBS["reply_budget"]
    assert budget.limit_name("code") == "max_tokens.code"
    assert knobs.KNOBS["request_timeout"].limit_name("code") == "timeout_s"


def test_the_limits_a_verdict_waits_on_come_from_the_registry():
    got = reasons.limits()
    assert got["max_tokens.code"] == knobs.KNOBS["reply_budget"].default("code")
    assert got["timeout_s"] == knobs.KNOBS["request_timeout"].default("")
    assert got["download_gib"] == pytest.approx(60.0)
    assert set(got) >= {"max_tokens", "timeout_s", "load_timeout_s", "download_gib"}


def test_every_sensitivity_probe_is_a_registered_knob():
    assert set(probes.PROBES) == {k.probe for k in knobs.KNOBS.values() if k.probe}


def test_a_probe_sweeps_the_range_its_knob_declares(monkeypatch):
    seen = {}

    def fake(name, default, values, run, **kw):
        seen[name] = (default, tuple(values))
        return None

    monkeypatch.setattr(probes, "measure", fake)
    monkeypatch.setattr(probes, "verdicts", lambda **kw: {})
    probes.probe_dead_days()
    k = knobs.KNOBS["dead_days"]
    assert seen["UPSTREAM_DEAD_DAYS"] == (k.default(""), tuple(k.values))


def test_no_new_gating_constant_is_unregistered():
    found = knobs.unregistered(knobs.inventory(REPO))
    new = sorted(set(found) - set(_backlog()))
    assert not new, ("register these in harness/knobs.py, or name why one gates nothing in "
                     "knobs.NOT_GATING:\n  " + "\n  ".join(new))


def test_the_knob_backlog_only_shrinks():
    found = set(knobs.unregistered(knobs.inventory(REPO)))
    gone = sorted(set(_backlog()) - found)
    assert not gone, "registered or gone: remove from tests/gauntlet/knob_backlog.json:\n  " + "\n  ".join(gone)


def test_a_constant_that_gates_nothing_says_why_and_is_still_found():
    found = set(knobs.inventory(REPO))
    for site, why in knobs.NOT_GATING.items():
        assert site in found, f"{site} is no longer found; remove it from NOT_GATING"
        assert why.strip(), site
        assert site not in {s for k in knobs.KNOBS.values() for s in k.sites}


def test_the_census_counts_registered_and_unregistered():
    got = knobs.census(REPO)
    assert got["registered"] == len({s for k in knobs.KNOBS.values() for s in k.sites
                                     if s in got["found"]})
    assert got["unregistered"] == len(knobs.unregistered(got["found"]))
    assert got["registered"] > 0 and got["unregistered"] > 0


def test_sensitivity_lists_the_knobs_with_their_lanes_and_limits(capsys):
    from harness import cli
    assert cli.main(["sensitivity", "--list", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    budget = next(k for k in got["knobs"] if k["name"] == "reply_budget")
    assert budget["limit"] == "max_tokens.{lane}" and "code" in budget["lanes"]


def test_sensitivity_inventory_counts_what_the_registry_covers(capsys):
    from harness import cli
    assert cli.main(["sensitivity", "--inventory", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["unregistered"] == len(got["unregistered_sites"]) == len(_backlog())
    assert got["registered"] >= 6
