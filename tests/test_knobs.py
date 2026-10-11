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


def test_the_inventory_reads_only_production_code():
    found = knobs.inventory(REPO)
    assert found and all(s.startswith(("harness/", "evals/", "scripts/", "gateway/")) for s in found)
    assert not any(s.startswith("evals/cases/") for s in found)
    assert "harness/completion.py:BUDGET" in found


def test_the_inventory_sees_every_shape_a_gating_value_takes_in_this_repo():
    found = set(knobs.inventory(REPO))
    for site in ("harness/heartbeat.py:STALL_S", "evals/runners/agent.py:STEP_TIMEOUT_S",
                 "harness/audio.py:speak(timeout)", "evals/run.py:SCREEN_PARAMS[steps]",
                 "scripts/serve-llamacpp.sh:LLAMACPP_SLEEP_IDLE"):
        assert site in found, site


def test_the_inventory_finds_the_time_and_retry_words_a_gate_is_named_with():
    names = ("CANCEL_GRACE_S", "STALL_S", "IDLE_S", "SERVE_WAIT_S", "RETRIES", "BACKOFF_S", "RETRY_DELAY",
             "ATTEMPTS", "SIZE_RETRIES", "IN_FLIGHT_SECONDS", "GRACE_SECONDS", "RETEST_AFTER_SECONDS",
             "START_S_PER_GIB", "SERVE_START_S", "DECODE_TOK_S", "DEADLINE_GRACE", "STOP_GRACE_S",
             "POLL_INTERVAL", "EFFECT_SIZE", "SLOT_CTX", "Z", "SECONDS_PER_TOKEN")
    src = "".join(f"{n} = 3\n" for n in names) + "STATUS = 3\nWORDS = 3\n"
    assert knobs.gating(src, "harness/m.py") == [f"harness/m.py:{n}" for n in names]


def test_the_inventory_finds_defaults_call_literals_table_entries_and_environment_defaults():
    src = ("import os\n"
           "SCREEN = {'width': 256, 'steps': 2, 'inner': {'temperature': 0.2}}\n"
           "BUDGET = {'code': 4000}\n"
           "WAIT = float(os.environ.get('SOH_WAIT_S') or 30)\n"
           "PORT = int(os.environ.get('SOH_PORT') or 8080)\n"
           "GRACE = os.getenv('SOH_GRACE', '5')\n"
           "def speak(text, timeout=120.0, speed=1.0, settle_s=3.0, levels=(1, 2), name='x'):\n"
           "    return run(text, timeout=30, check=True)\n"
           "class C:\n"
           "    def go(self, poll=0.5, max_tokens=None):\n"
           "        return get(max_new_tokens=64)\n"
           "def outer():\n"
           "    def inner(timeout=5):\n"
           "        pass\n")
    assert knobs.gating(src, "harness/m.py") == [
        "harness/m.py:SCREEN[steps]", "harness/m.py:SCREEN[inner][temperature]", "harness/m.py:BUDGET",
        "harness/m.py:environ(SOH_WAIT_S)", "harness/m.py:environ(SOH_GRACE)",
        "harness/m.py:speak(timeout)", "harness/m.py:speak(settle_s)", "harness/m.py:speak(levels)",
        "harness/m.py:speak->run(timeout)", "harness/m.py:C.go(poll)", "harness/m.py:C.go->get(max_new_tokens)",
        "harness/m.py:outer.inner(timeout)"]


def test_the_inventory_reads_shell_defaults_and_gateway_settings():
    sh = ('PORT="${SOH_PORT:-8081}"\n'
          'exec srv --idle "${SOH_SLEEP_IDLE:-300}" --ctx "${SOH_CTX:-16384}" --host "${SOH_HOST:-127.0.0.1}"\n')
    assert knobs.shell_defaults(sh, "scripts/x.sh") == ["scripts/x.sh:SOH_SLEEP_IDLE", "scripts/x.sh:SOH_CTX"]
    yml = ("model_list:\n  - model_name: a\n    litellm_params: {timeout: 5}\n"
           "litellm_settings:\n  drop_params: true\n  request_timeout: 600\n  num_retries: 2\n"
           "  cache_params: {ttl: 60}\n")
    assert knobs.gateway_settings(yml, "gateway/config.yaml") == [
        "gateway/config.yaml:litellm_settings.request_timeout", "gateway/config.yaml:litellm_settings.num_retries",
        "gateway/config.yaml:litellm_settings.cache_params.ttl"]


def test_a_table_entry_and_a_method_default_resolve():
    from evals import run
    assert knobs.resolve("evals/run.py:SCREEN_PARAMS[steps]") == run.SCREEN_PARAMS["steps"]
    assert knobs.resolve("harness/audio.py:speak(timeout)") == 120.0


def test_a_new_unregistered_retry_constant_fails_the_backlog_ratchet(tmp_path):
    import subprocess
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "fixture.py").write_text("RETRIES = 3\nNAME = 'x'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    found = knobs.unregistered(knobs.inventory(tmp_path))
    assert found == ["harness/fixture.py:RETRIES"]
    assert set(found) - set(_backlog()) == {"harness/fixture.py:RETRIES"}


def test_every_knob_names_a_value_that_exists():
    for k in knobs.KNOBS.values():
        for site in k.sites:
            assert knobs.resolve(site) is not None, site


def test_every_knob_s_range_holds_its_default_for_every_lane_it_affects():
    for k in knobs.KNOBS.values():
        for lane in k.lanes or ("",):
            assert k.default(lane) in k.values_for(lane), (k.name, lane, k.default(lane))


def test_every_knob_s_lanes_are_lanes():
    for k in knobs.KNOBS.values():
        assert set(k.lanes) <= set(lanes.ALL), k.name


def test_a_knob_that_gates_an_eval_names_the_limit_that_shows_it_binding():
    for k in knobs.KNOBS.values():
        if k.lanes:
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


def test_eval_7b_slots_and_slot_context_are_knobs_and_every_slot_context_clears_the_floor():
    from harness import context
    slots, slot_ctx = knobs.KNOBS["eval7b_slots"], knobs.KNOBS["eval7b_slot_ctx"]
    assert slots.default() == context.EVAL_7B_SLOTS and slot_ctx.default() == context.EVAL_7B_SLOT_CTX
    assert context.MIN_SLOT_CTX == 3072
    assert all(v >= context.MIN_SLOT_CTX for v in (*slot_ctx.values, slot_ctx.default()))


def test_ornith_slots_and_slot_context_are_knobs_and_every_slot_reaches_the_long_floor():
    from harness import context
    slots, slot_ctx = knobs.KNOBS["ornith_slots"], knobs.KNOBS["ornith_slot_ctx"]
    assert slots.default() == context.ORNITH_SLOTS and slot_ctx.default() == context.ORNITH_SLOT_CTX
    assert context.MIN_LONG_SLOT_CTX > 65536
    assert all(v >= context.MIN_LONG_SLOT_CTX for v in (*slot_ctx.values, slot_ctx.default()))
