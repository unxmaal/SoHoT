"""The knob registry: every outcome-gating constant declares its range, lanes and binding signal (#636)."""
import json
import subprocess
from pathlib import Path

import pytest

from harness import knobs, lanes, probes, reasons

REPO = Path(__file__).resolve().parent.parent
BACKLOG_DIR = REPO / "tests" / "gauntlet" / "knob_backlog"


def _backlog_file(site: str) -> Path:
    """One backlog file per source directory, so PRs in different directories never touch the same file (#751)."""
    return BACKLOG_DIR / (site.split(":", 1)[0].rsplit("/", 1)[0].replace("/", "_") + ".txt")


def _backlog():
    return [line for path in sorted(BACKLOG_DIR.glob("*.txt"))
            for line in path.read_text(encoding="utf-8").splitlines()]


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
                "class C:\n    name = 'x'\n    TIMEOUT_S = None\n")
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
                 "harness/feeds.py:fetch(timeout)", "evals/run.py:SCREEN_PARAMS[width]",
                 "scripts/serve-llamacpp.sh:LLAMACPP_TIMEOUT"):
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
        "harness/m.py:SCREEN[width]", "harness/m.py:SCREEN[steps]", "harness/m.py:SCREEN[inner][temperature]",
        "harness/m.py:BUDGET", "harness/m.py:environ(SOH_WAIT_S)", "harness/m.py:environ(SOH_PORT)",
        "harness/m.py:environ(SOH_GRACE)",
        "harness/m.py:speak(timeout)", "harness/m.py:speak(settle_s)", "harness/m.py:speak(levels)",
        "harness/m.py:speak->run(timeout)", "harness/m.py:C.go(poll)", "harness/m.py:C.go->get(max_new_tokens)",
        "harness/m.py:outer.inner(timeout)"]


def test_the_inventory_reads_shell_defaults_and_gateway_settings():
    sh = ('PORT="${SOH_PORT:-8081}"\n'
          'exec srv --idle "${SOH_SLEEP_IDLE:-300}" --ctx "${SOH_CTX:-16384}" --host "${SOH_HOST:-127.0.0.1}"\n')
    assert knobs.shell_defaults(sh, "scripts/x.sh") == [
        "scripts/x.sh:SOH_PORT", "scripts/x.sh:SOH_SLEEP_IDLE", "scripts/x.sh:SOH_CTX"]
    yml = ("model_list:\n  - model_name: a\n    litellm_params: {timeout: 5}\n"
           "litellm_settings:\n  drop_params: true\n  request_timeout: 600\n  num_retries: 2\n"
           "  cache_params: {ttl: 60}\n")
    assert knobs.gateway_settings(yml, "gateway/config.yaml") == [
        "gateway/config.yaml:litellm_settings.request_timeout", "gateway/config.yaml:litellm_settings.num_retries",
        "gateway/config.yaml:litellm_settings.cache_params.ttl"]


def test_a_table_entry_and_a_method_default_resolve():
    from evals import run
    assert knobs.resolve("evals/run.py:SCREEN_PARAMS[width]") == run.SCREEN_PARAMS["width"]
    assert knobs.resolve("harness/feeds.py:fetch(timeout)") == 30.0


def test_a_new_unregistered_retry_constant_fails_the_backlog_ratchet(tmp_path):
    import subprocess
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "fixture.py").write_text("NAME = 'x'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _assert_no_new_gating_site(tmp_path)
    (tmp_path / "harness" / "fixture.py").write_text("RETRIES = 3\nNAME = 'x'\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"harness/fixture\.py:RETRIES"):
        _assert_no_new_gating_site(tmp_path)


def test_a_second_call_literal_in_the_same_scope_is_a_new_site():
    one = "def f(a):\n    subprocess.run(a, timeout=5)\n"
    two = one + "    subprocess.run(a, timeout=600)\n"
    assert knobs.gating(one, "harness/m.py") == ["harness/m.py:f->subprocess.run(timeout)"]
    assert knobs.gating(two, "harness/m.py") == ["harness/m.py:f->subprocess.run(timeout)",
                                                 "harness/m.py:f->subprocess.run(timeout)#2"]


def test_class_and_dataclass_field_defaults_are_found():
    src = ("class Engine:\n    name: str = 'x'\n    timeout: float = 900.0\n    stream: bool = False\n"
           "class Kill:\n    recover_seconds = 5\n    budget = 3\n    cost_s: float = 1.5\n    TIMEOUT_S = 3\n")
    assert knobs.gating(src, "harness/m.py") == [
        "harness/m.py:Engine.timeout", "harness/m.py:Kill.recover_seconds", "harness/m.py:Kill.budget",
        "harness/m.py:Kill.cost_s", "harness/m.py:Kill.TIMEOUT_S"]
    found = set(knobs.inventory(REPO))
    for site in ("harness/engines.py:Engine.timeout", "harness/chaos.py:ServerKill.recover_seconds",
                 "harness/inspect.py:Fit.upstream_idle_days", "harness/github.py:Client.budget",
                 "harness/verify.py:Task.cost_s"):
        assert site in found, site
    assert knobs.resolve("harness/engines.py:Engine.timeout") == 900.0


def test_every_numeric_environment_default_and_table_entry_is_found_whatever_its_name():
    src = ("import os\nN = int(os.environ.get('LLAMACPP_PARALLEL') or 1)\n"
           "STRENGTH = {'lowres': 0.5, 'name': 'x'}\nweights = {'a': 2}\n")
    assert knobs.gating(src, "harness/m.py") == [
        "harness/m.py:environ(LLAMACPP_PARALLEL)", "harness/m.py:STRENGTH[lowres]", "harness/m.py:weights[a]"]
    assert "harness/context.py:environ(LLAMACPP_CTX)" in knobs.inventory(REPO)


def test_a_timeout_passed_positionally_is_found():
    src = ("def stop(proc, t, xs):\n    proc.wait(10)\n    t.join(5)\n    ', '.join(xs)\n    proc.wait()\n")
    assert knobs.gating(src, "harness/m.py") == ["harness/m.py:stop->proc.wait(timeout)",
                                                 "harness/m.py:stop->t.join(timeout)"]
    found = set(knobs.inventory(REPO))
    assert "harness/chaos.py:kill->server.proc.wait(timeout)" in found
    assert "harness/chaos.py:run_screen->proc.wait(timeout)" in found


def test_every_site_form_the_inventory_reports_resolves_so_it_can_be_registered():
    assert knobs.resolve("harness/engines.py:_mflux->Engine(timeout)") > 0
    assert knobs.resolve("harness/context.py:environ(LLAMACPP_CTX)") == 16384
    assert knobs.resolve("scripts/serve-llamacpp.sh:LLAMACPP_TIMEOUT") == 7200
    unresolved = []
    for site in knobs.inventory(REPO):
        try:
            knobs.resolve(site)
        except Exception as e:
            unresolved.append(f"{site}: {e!r}")
    assert not unresolved, "\n".join(unresolved)


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


def _assert_no_new_gating_site(root):
    found = knobs.unregistered(knobs.inventory(root))
    new = sorted(set(found) - set(_backlog()))
    assert not new, ("register these in an area of harness/knobs/, or name why one gates nothing in "
                     "that area's NOT_GATING:\n  " + "\n  ".join(new))


def test_no_new_gating_constant_is_unregistered():
    _assert_no_new_gating_site(REPO)


def test_the_knob_backlog_only_shrinks():
    found = set(knobs.unregistered(knobs.inventory(REPO)))
    gone = sorted(set(_backlog()) - found)
    assert not gone, "registered or gone: remove from tests/gauntlet/knob_backlog/:\n  " + "\n  ".join(
        f"{_backlog_file(s).name}: {s}" for s in gone)


def test_each_knob_backlog_file_is_sorted_unique_and_holds_only_its_own_directory():
    files = sorted(BACKLOG_DIR.glob("*.txt"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines and text.endswith("\n") and "\n\n" not in text, path.name
        assert lines == sorted(set(lines)), f"{path.name}: one site per line, sorted, no repeats"
        wrong = [s for s in lines if _backlog_file(s) != path]
        assert not wrong, f"{path.name} holds sites of another directory: {wrong}"


def test_the_knob_backlog_does_not_merge_by_union_which_cannot_delete_a_line():
    got = subprocess.run(["git", "check-attr", "merge", "--", "tests/gauntlet/knob_backlog/harness.txt"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert got.strip().endswith(": merge: unspecified")


def test_the_legacy_values_old_receipts_ran_at_are_exactly_these():
    assert knobs.UNRECORDED == {
        "code_check_timeout": 15.0, "audio_timeout": 120.0, "chrome_render_timeout": 60.0,
        "svg_render_timeout": 30.0, "claude_code_timeout": 600.0, "needle_serve_start": 60.0,
        "agent_steps_scale": 1.0, "agent_case_timeout": 900.0, "agent_step_timeout": 300.0,
        "tts_token_floor": 8.0, "ocr_max_new_tokens": 512}
    assert all(knobs.KNOBS[n].unrecorded == v and knobs.KNOBS[n].receipt == "knobs"
               for n, v in knobs.UNRECORDED.items())


def test_a_legacy_value_is_history_on_its_knob_and_never_an_inventory_site():
    found = knobs.inventory(REPO)
    assert not [s for s in found if s.startswith("harness/knobs/") or "UNRECORDED" in s]
    assert not knobs.not_gating("harness/other.py:UNRECORDED[audio_timeout]")


def test_every_knob_and_not_gating_entry_lives_in_one_area_module():
    areas = knobs.areas()
    assert len(areas) > 1 and "base" not in areas
    names = [n for mod in areas.values() for n in knobs.entries(mod)]
    assert sorted(names) == sorted(knobs.KNOBS) and len(names) == len(set(names))
    sites = [s for mod in areas.values() for s in getattr(mod, "NOT_GATING", {})]
    assert sorted(sites) == sorted(knobs.NOT_GATING) and len(sites) == len(set(sites))


def test_a_knob_registered_in_two_areas_is_refused():
    one = knobs.Knob("twice", ("harness/a.py:X",), (1,))
    with pytest.raises(ValueError, match="twice"):
        knobs.collect({"a": [one], "b": [("twice", one)]})


def test_registration_order_does_not_change_the_registry():
    a = knobs.Knob("a_knob", ["harness/a.py:X"], [1, 2])
    b = knobs.Knob("b_knob", ("harness/b.py:Y",), (3,), unrecorded=3)
    one, _ = knobs.collect({"x": [a], "y": [b]})
    two, _ = knobs.collect({"x": [b], "y": [a]})
    assert one == two and list(one) == ["a_knob", "b_knob"]
    assert one["a_knob"].sites == ("harness/a.py:X",) and one["a_knob"].values == (1, 2)


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


def test_an_argument_default_or_call_keyword_is_found_by_the_same_name_words_as_a_constant():
    src = ("def check_html(path, min_ink=0.0005):\n    pass\n"
           "class RepairRunner:\n    def __init__(self, attempts=3):\n        pass\n"
           "def run(c):\n    c.ask(retries=1, etag_timeout=5, max_length=80, name=2)\n")
    assert knobs.gating(src, "harness/m.py") == [
        "harness/m.py:check_html(min_ink)", "harness/m.py:RepairRunner.__init__(attempts)",
        "harness/m.py:run->c.ask(retries)", "harness/m.py:run->c.ask(etag_timeout)",
        "harness/m.py:run->c.ask(max_length)"]
    found = set(knobs.inventory(REPO))
    for site in ("harness/checks/render.py:check_html(min_ink)", "evals/runners/repair.py:RepairRunner.__init__(attempts)",
                 "harness/checks/render.py:_remove_tree(attempts)", "harness/checks/render.py:_remove_tree(delay)"):
        assert site in found, site
    assert knobs.resolve("harness/checks/render.py:check_html(min_ink)") == 0.0005


def test_a_second_function_with_its_own_ink_threshold_fails_the_ratchet(tmp_path):
    import subprocess
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "fixture.py").write_text("NAME = 'x'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _assert_no_new_gating_site(tmp_path)
    (tmp_path / "harness" / "fixture.py").write_text("def check_svg(p, min_ink=0.001):\n    pass\n", encoding="utf-8")
    with pytest.raises(AssertionError, match=r"harness/fixture\.py:check_svg\(min_ink\)"):
        _assert_no_new_gating_site(tmp_path)


def test_every_numeric_shell_default_is_found_whatever_its_name():
    src = 'TOP="${DISCOVER_TOP:-3}"\nPORT="${PORT:-8080}"\nNAME="${NAME:-x}"\n'
    assert knobs.shell_defaults(src, "scripts/s.sh") == ["scripts/s.sh:DISCOVER_TOP", "scripts/s.sh:PORT"]
    found = set(knobs.inventory(REPO))
    for site in ("scripts/serve-discover.sh:DISCOVER_TOP", "scripts/serve-discover.sh:DISCOVER_BUDGET_GIB",
                 "scripts/serve-llamacpp.sh:LLAMACPP_GPU_LAYERS"):
        assert site in found, site


def test_a_new_entry_in_a_table_named_as_gating_nothing_is_not_exempt():
    assert knobs.not_gating("harness/context.py:CACHE_BYTES[f16]")
    assert not knobs.not_gating("harness/context.py:CACHE_BYTES[q2_k]")
    assert not knobs.not_gating("harness/usage.py:_UNITS[w]")


def test_a_limit_two_knobs_share_takes_the_value_of_the_first_by_name_whatever_the_registration_order(monkeypatch):
    shared = [k for k in knobs.KNOBS.values() if k.limit == "tts_tokens"]
    assert [k.name for k in shared] == ["tts_cap_fill", "tts_token_floor"]
    want = knobs.limits()["tts_tokens"]
    assert want == shared[0].limit_value("")
    monkeypatch.setattr(knobs, "KNOBS", dict(reversed(list(knobs.KNOBS.items()))))
    assert knobs.limits()["tts_tokens"] == want


def test_each_area_lists_its_knobs_in_name_order_so_two_prs_insert_at_different_lines():
    for area, mod in knobs.areas().items():
        names = knobs.entries(mod)
        assert names == sorted(names), f"harness/knobs/{area}.py: list KNOBS in name order"
