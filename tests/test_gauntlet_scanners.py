"""Repo-wide scanners for the tier-1 gauntlet classes, each proven to fire and to stay quiet (#492 C)."""

from pathlib import Path

from gauntlet import scanners as gscanners

from tests import tree_cache
from tests.gauntlet import owner_verbs, scanners

REPO = Path(__file__).resolve().parent.parent


def test_a_live_home_derived_outside_paths_is_found():
    src = ("from pathlib import Path\nimport os\n"
           "A = Path.home() / \"localharness\" / \"omnisvg\"\n"
           "B = Path.home() / \"localharness/runs/x\"\n"
           "C = os.path.join(os.path.expanduser(\"~\"), \"localharness\")\n"
           "D = Path(\"~/localharness/x\").expanduser()\n"
           "OUTDIR = paths.outputs()\n"
           "def f(d=paths.home()):\n    return d\n")
    got = scanners.live_home_python(src, "evals/runners/x.py")
    assert [f.split(":")[1] for f in got] == ["3", "4", "5", "6", "7", "8"]
    sh = "#!/usr/bin/env bash\nDEST=\"$HOME/localharness/x\"\n"
    assert [f.split(":")[1] for f in scanners.live_home_shell(sh, "s.sh")] == ["2"]


def _quiet_then_fires(scan, innocent, bad, rel):
    # Quiet on the innocent text, and firing once the bad line joins it: quiet for the right reason.
    assert scan(innocent, rel) == []
    assert scan(innocent + bad, rel) != []


def test_a_live_home_asked_of_paths_is_left_alone():
    innocent = ("from harness import paths\nfrom pathlib import Path\n"
                "def out():\n    return paths.home() / \"omnisvg\"\n"
                "TOOLS = Path.home() / \".local/share/uv/tools/mflux/bin\"\n"
                "HF = Path.home() / \".cache\" / \"huggingface\"\n"
                "NOTE = \"see ~/localharness in the README\"\n")
    _quiet_then_fires(scanners.live_home_python, innocent,
                      "X = Path.home() / \"localharness\"\n", "evals/runners/x.py")
    assert scanners.live_home_python("DEFAULT_HOME = Path.home() / \"localharness\"\n", "harness/paths.py") == []
    sh = ("#!/usr/bin/env bash\nDEST=\"${OMNISVG_HOME:-${LOCALHARNESS_HOME:-$HOME/localharness}/omnisvg}\"\n"
          "# default: $HOME/localharness\nCACHE=\"$HOME/.cache/huggingface\"\n")
    _quiet_then_fires(scanners.live_home_shell, sh, "cp x ~/localharness/\n", "s.sh")


def _shellish(path):
    return gscanners.is_shell(path) or path.name == "Makefile"


def _tests_only(rel):
    return rel.startswith("tests/")


def _fail_with(found, why):
    assert not found, why + ":\n  " + "\n  ".join(found)


def test_no_function_has_a_mutable_default():
    _fail_with(tree_cache.scan_tree(REPO, gscanners.mutable_defaults, gscanners.is_python),
               "a mutable default is shared by every call; default to None and build it inside")


def test_no_shell_script_ignores_a_failure_it_could_see():
    _fail_with(tree_cache.scan_tree(REPO, gscanners.unchecked_status_shell, gscanners.is_shell),
               "set -o pipefail, or end the pipeline in a `grep -q` probe; guard each cd without errexit")


def test_no_test_binds_or_writes_a_fixed_shared_resource():
    _fail_with(tree_cache.scan_tree(REPO, gscanners.fixed_resources, gscanners.is_python, _tests_only),
               "two suites at once (parallel worktrees) collide on a fixed resource; ask the OS for one")


def test_the_live_home_is_derived_only_in_harness_paths():
    found = (tree_cache.scan_tree(REPO, scanners.live_home_python, gscanners.is_python)
             + tree_cache.scan_tree(REPO, scanners.live_home_shell, _shellish))
    _fail_with(found, "conftest redirects LOCALHARNESS_HOME; a path derived any other way is the live one")


def test_a_hand_flip_of_the_offline_guard_is_found():
    src = ("import os\nfrom huggingface_hub import constants\n"
           "os.environ[\"HF_HUB_OFFLINE\"] = \"0\"\n"
           "constants.HF_HUB_OFFLINE = False\n"
           "os.environ.pop(\"HF_HUB_OFFLINE\", None)\n"
           "environ.setdefault(\"HF_HUB_OFFLINE\", \"0\")\n"
           "os.environ.update(HF_HUB_OFFLINE=\"0\")\n"
           "setattr(constants, \"HF_HUB_OFFLINE\", False)\n"
           "del os.environ[\"HF_HUB_OFFLINE\"]\n"
           "os.putenv(\"HF_HUB_OFFLINE\", \"0\")\n")
    got = scanners.offline_flips(src, "harness/x.py")
    assert [f.split(":")[1] for f in got] == [str(n) for n in range(3, 11)]


def test_the_shared_offline_guard_and_a_child_env_are_left_alone():
    innocent = ("import os, subprocess\nfrom harness import env\n"
                "with env.online():\n    go()\n"
                "was = os.environ.get(\"HF_HUB_OFFLINE\")\n"
                "subprocess.run(cmd, env=dict(os.environ, HF_HUB_OFFLINE=\"0\"))\n")
    _quiet_then_fires(scanners.offline_flips, innocent,
                      "os.environ[\"HF_HUB_OFFLINE\"] = \"0\"\n", "harness/x.py")
    owner = ("def online():\n    os.environ[\"HF_HUB_OFFLINE\"] = \"0\"\n"
             "def apply(environ):\n    environ.setdefault(\"HF_HUB_OFFLINE\", \"1\")\n")
    _quiet_then_fires(scanners.offline_flips, owner,
                      "def other():\n    os.environ[\"HF_HUB_OFFLINE\"] = \"0\"\n", "harness/env.py")


def test_no_code_flips_the_offline_guard_except_through_env_online():
    _fail_with(tree_cache.scan_tree(REPO, scanners.offline_flips, gscanners.is_python,
                                   lambda rel: not _tests_only(rel)),
               "huggingface_hub reads HF_HUB_OFFLINE once at import, so the env var alone lifts nothing; "
               "wrap the call in harness.env.online() (#931, RULE #208)")


def test_a_sum_over_a_listing_is_found():
    src = ("def a(data):\n    return sum(s.get(\"size\") or 0 for s in data.get(\"siblings\", []))\n"
           "def b(siblings):\n    sizes = [f[\"size\"] for f in siblings]\n    return sum(sizes)\n"
           "def c(card):\n    t = 0\n    for f in card.siblings:\n        t += f.size\n    return t\n")
    got = scanners.listing_sums(src, "harness/x.py")
    assert [f.split(":")[1] for f in got] == ["2", "5", "9"]


def test_a_sum_inside_variants_or_over_one_variant_is_left_alone():
    innocent = ("def shard_sets(siblings):\n    parts = {f[\"rfilename\"]: f[\"size\"] for f in siblings}\n"
                "    return sum(parts.values())\n"
                "def total(files):\n    return sum(s for _, s in files)\n"
                "def names(siblings):\n    return sum(1 for f in siblings if f.get(\"rfilename\"))\n")
    bad = "def d(data):\n    return sum(s.get(\"size\") or 0 for s in data[\"siblings\"])\n"
    _quiet_then_fires(scanners.listing_sums, innocent, bad, "harness/x.py")
    assert scanners.listing_sums(bad, scanners.LISTING_OWNER) == []


def test_no_code_adds_up_a_listing_outside_variants():
    _fail_with(tree_cache.scan_tree(REPO, scanners.listing_sums, gscanners.is_python,
                                   lambda rel: rel.startswith("harness/")),
               "a listing's sum is the repo, not what runs; hf_facts and card_description reported it "
               "after the verdict stopped (#964, gauntlet one-question-two-answers)")


# Inventories: reported, never grown. Lower a pin when a fix lands.
SWALLOWED_PIN = 59
CONFIG_LESS_PIN = 147


def test_swallowed_errors_are_an_inventory_that_only_shrinks():
    found = (tree_cache.scan_tree(REPO, gscanners.swallowed_python, gscanners.is_python)
             + tree_cache.scan_tree(REPO, gscanners.swallowed_shell, _shellish))
    msg = gscanners.ratchet(found, SWALLOWED_PIN, "swallowed errors (empty except, bare except, || true)")
    assert msg is None, msg


def test_numbers_without_their_configuration_are_an_inventory_that_only_shrinks():
    from harness import assertions
    found = [str(c) for c in assertions.collect(REPO) if c.config_less]
    msg = gscanners.ratchet(found, CONFIG_LESS_PIN, "numbers in prose with no configuration beside them")
    assert msg is None, msg


_AUDIT = ('VERDICTS = ("stale_rows", "plain_rows")\n'
          'REPAIRED_BY = {"stale_rows": heartbeat.FIXED_ROWS}\n'
          'def _stale_rows(conn):\n    return ms.stale(conn, ms.here())\n'
          'def _plain_rows(conn):\n    return [r for r in conn.execute("SELECT 1")]\n')
_LOOP = ('def _fix_rows():\n    began = heartbeat.clock()\n    ms.requeue_stale(ms.connect())\n'
         '    heartbeat.mark(heartbeat.FIXED_ROWS, began)\n')
_STORE = {"harness/memory_store/revisit.py":
          'def here():\n    return 1\ndef stale(conn, at):\n    return []\n'
          'def requeue_stale(conn):\n    return [retract(r) for r in stale(conn, here())]\n'
          'def retract(r):\n    return r\ndef other(conn):\n    return []\n'
          'def fix_other(conn):\n    for r in other(conn):\n        retract(r)\n'}


def test_a_loop_repaired_check_that_waits_on_nothing_is_found():
    got = scanners.unwaited_repairs(_AUDIT.replace('REPAIRED_BY = {"stale_rows": heartbeat.FIXED_ROWS}',
                                                   'REPAIRED_BY = {}'), _LOOP, _STORE)
    assert len(got) == 1 and "stale_rows is repaired by the loop's _fix_rows" in got[0]
    got = scanners.unwaited_repairs(_AUDIT, _LOOP.replace("heartbeat.mark(heartbeat.FIXED_ROWS, began)",
                                                          "heartbeat.mark(heartbeat.OTHER, began)"), _STORE)
    assert len(got) == 1 and "waits on heartbeat.FIXED_ROWS" in got[0]


def test_a_check_its_repair_marks_or_no_loop_step_touches_is_left_alone():
    assert scanners.unwaited_repairs(_AUDIT, _LOOP, _STORE) == []
    other = _AUDIT + 'def _plain_rows(conn):\n    return ms.other(conn)\n'
    assert scanners.unwaited_repairs(other, _LOOP, _STORE) == []
    assert scanners.unwaited_repairs(other, _LOOP + 'def _peek():\n    ms.other(ms.connect())\n', _STORE) == []
    fires = _LOOP + 'def _also():\n    ms.fix_other(ms.connect())\n'
    assert len(scanners.unwaited_repairs(other, fires, _STORE)) == 1


def test_every_live_audit_check_a_loop_step_repairs_waits_on_that_steps_heartbeat_key():
    stores = {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
              for p in sorted((REPO / "harness/memory_store").glob("*.py"))}
    _fail_with(scanners.unwaited_repairs((REPO / scanners.AUDIT_FILE).read_text(encoding="utf-8"),
                                         (REPO / scanners.LOOP_FILE).read_text(encoding="utf-8"), stores),
               "a check whose backlog a loop step repairs is an inventory until that step has run; it gated the "
               "deploy smoke on the backlog it started with (#972, #904, gauntlet a-rule-change-leaves-old-decisions-standing)")


_TIMED = "import time\n\ndef test_x(r):\n    started = time.perf_counter()\n    r.go()\n    after = time.perf_counter()\n"


def test_an_upper_bound_on_measured_wall_time_is_found():
    for bad in ("    assert time.perf_counter() - started < 1.0\n",
                "    took = after - started\n    assert took <= 2\n",
                "    assert r.seconds < 0.4\n",
                "    assert 15 > after - started\n",
                "    assert abs(r.stamp - time.time()) < 60\n",
                "    assert 0 < r.out['wall_s'] < 3 * 0.5\n"):
        assert len(scanners.wall_bounds(_TIMED + bad, "tests/test_t.py")) == 1, bad


def test_order_lower_bounds_and_brackets_of_measured_time_are_left_alone():
    innocent = _TIMED + ("    assert r.seconds >= 0.4 and after - started >= r.seconds\n"
                         "    assert started <= r.stamp <= after + 60 - 0.5\n"
                         "    assert r.first_s < r.ttft_s <= after - started\n"
                         "    assert r.rate / r.capped_s < 5\n")
    _quiet_then_fires(scanners.wall_bounds, innocent, "    assert after - started < 5\n", "tests/test_t.py")


def test_a_waived_fake_clock_test_is_left_alone_and_only_that_test():
    src = _TIMED + "    assert r.seconds < 0.4\n"
    assert scanners.wall_bounds(src, "tests/test_t.py", waivers={"tests/test_t.py:test_x": "fake clock"}) == []
    assert scanners.wall_bounds(src, "tests/test_t.py", waivers={"tests/test_t.py:test_y": "fake clock"}) != []


def test_every_wall_bound_waiver_names_a_test_that_exists():
    import ast
    for site in scanners.WALL_BOUND_WAIVERS:
        rel, name = site.split(":")
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        assert name in {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}, site


def test_no_test_bounds_measured_wall_time_from_above():
    _fail_with(tree_cache.scan_tree(REPO, scanners.wall_bounds, gscanners.is_python, _tests_only),
               "a loaded machine (make check -n auto beside other suites) overruns any upper bound on wall time; "
               "assert order, a count, a lower bound or a structural fact, or inject the clock (#1423)")


def test_production_code_that_tells_a_stand_in_from_the_real_function_is_found():
    for bad in ("if getattr(ms.this_machine, \"__module__\", \"\") != __name__:\n    pass\n",
                "if ms.this_machine.__module__ == __name__:\n    pass\n",
                "if ms.this_machine is not this_machine:\n    pass\n",
                "ok = hasattr(fn, \"__module__\")\n"):
        assert len(scanners.double_sniffs(bad, "harness/m.py")) == 1, bad


def test_identity_checks_that_do_not_sniff_for_a_double_are_left_alone():
    innocent = ("if fn is None or self.conn is not conn_b:\n    pass\n"
                "name = getattr(fn, \"__name__\", \"\")\nkind = type(e).__qualname__\n")
    _quiet_then_fires(scanners.double_sniffs, innocent, "if ms.this_fingerprint is this_fingerprint:\n    pass\n",
                      "harness/m.py")


def test_no_production_code_sniffs_for_a_test_double():
    _fail_with(tree_cache.scan_tree(REPO, scanners.double_sniffs, gscanners.is_python, lambda rel: not _tests_only(rel)),
               "production code that checks whether a name was replaced runs one path under test and another live; "
               "tests name the machine at environment.identity instead (#1437, #451)")


def test_a_test_that_replaces_this_machine_is_found():
    src = ("def test_x(monkeypatch):\n    monkeypatch.setattr(ms, \"this_machine\", lambda: {})\n"
           "    monkeypatch.setattr(\"harness.memory_store.this_fingerprint\", lambda: \"f\")\n")
    assert [f.split(":")[1] for f in scanners.machine_stand_ins(src, "tests/test_x.py")] == ["2", "3"]


def test_a_test_that_names_the_machine_at_the_seam_is_left_alone():
    innocent = ("def test_x(monkeypatch, machine_is):\n    machine_is({\"hw_model\": \"T,1\"})\n"
                "    monkeypatch.setattr(ms.machines, \"_THIS_MACHINE\", None)\n"
                "    monkeypatch.setattr(environment, \"identity\", lambda: {})\n")
    _quiet_then_fires(scanners.machine_stand_ins, innocent,
                      "    monkeypatch.setattr(served, \"this_machine\", lambda: \"f\")\n", "tests/test_x.py")


def test_no_test_replaces_this_machine():
    _fail_with(tree_cache.scan_tree(REPO, scanners.machine_stand_ins, gscanners.is_python, _tests_only),
               "a replaced this_machine reaches some callers and not this_fingerprint or the gateway; "
               "use conftest machine_is / machine_has (#1437)")


def test_a_hub_download_outside_the_allowed_sites_is_found():
    src = ("import huggingface_hub\nfrom huggingface_hub import snapshot_download as grab\n"
           "def a(repo):\n    return huggingface_hub.hf_hub_download(repo, \"x.gguf\")\n"
           "def b(repo):\n    return grab(repo)\n"
           "ARGV = [\"uv\", \"run\", \"hf download org/model\"]\n")
    got = scanners.hf_downloads(src, "harness/x.py")
    assert [f.split(":")[1] for f in got] == ["2", "4", "7"]


def test_a_hub_download_inside_the_allowed_sites_or_only_named_is_left_alone():
    innocent = ('"""Never calls snapshot_download; the screen fetches through harness.fetching."""\n'
                "from huggingface_hub import HfApi\n# hf download org/x by hand\n"
                "def size(repo):\n    return HfApi().model_info(repo)\n")
    bad = "def c(repo):\n    from huggingface_hub import snapshot_download\n    return snapshot_download(repo)\n"
    _quiet_then_fires(scanners.hf_downloads, innocent, bad, "harness/x.py")
    assert scanners.hf_downloads(bad, "harness/fetching.py") == []
    assert scanners.hf_downloads_shell("# hf download org/x\necho ok\n", "scripts/x.sh") == []
    assert scanners.hf_downloads_shell("uv run hf download org/x\n", "scripts/x.sh") != []
    assert scanners.hf_downloads_shell("uv run hf download org/x\n", "scripts/setup-omnisvg.sh") == []


def test_only_the_allowed_sites_download_from_the_hub():
    _fail_with(tree_cache.scan_tree(REPO, scanners.hf_downloads, gscanners.is_python,
                                   lambda rel: not rel.startswith(("tests/", "evals/cases/")))
               + tree_cache.scan_tree(REPO, scanners.hf_downloads_shell, gscanners.is_shell),
               "never download what cannot be tested near-immediately: a test fetches what it runs through "
               "harness.fetching, and anything else is a pinned tool named in DOWNLOAD_SITES (#2015)")


def test_every_allowed_download_site_still_downloads():
    stale = [rel for rel in scanners.DOWNLOAD_SITES
             if not any(d in (REPO / rel).read_text(encoding="utf-8")
                        for d in ("snapshot_download", "hf_hub_download", "hf download"))]
    assert not stale, f"an allowed site that no longer downloads leaves a hole for the next one: {stale}"


def _cli(*extra):
    import argparse
    ap = argparse.ArgumentParser(prog="soh")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("restart")
    hold = sub.add_parser("hold")
    hold.add_argument("scope", choices=["gpu", "status"])
    for name in extra:
        sub.add_parser(name)
    return owner_verbs.verb_paths(ap)


def _owner_found(paths, argvs=(("restart", "{}"), ("hold", "gpu")), exempt=None, not_owner=None):
    bound = owner_verbs.bound(argvs, paths)
    return owner_verbs.check(paths, bound, exempt or {}, not_owner or {"hold status": "read-only"})


def test_the_parsers_verbs_include_a_positional_choice_as_a_verb():
    assert ("hold", "gpu") in _cli() and ("hold",) in _cli()


def test_an_owner_verb_with_no_action_and_no_exemption_is_found():
    found = _owner_found(_cli("wipe"))
    assert len(found) == 1 and "'wipe' has no status-page Action" in found[0]


def test_a_bound_or_exempted_verb_is_left_alone_and_the_bad_line_still_fires_beside_it():
    assert _owner_found(_cli()) == []
    assert _owner_found(_cli("wipe"), exempt={"wipe": "too dangerous for one tap"}) == []
    assert len(_owner_found(_cli("wipe", "purge"), exempt={"wipe": "too dangerous for one tap"})) == 1


def test_an_exemption_for_a_verb_the_parser_no_longer_has_is_found():
    found = _owner_found(_cli(), exempt={"gone": "was one tap"})
    assert len(found) == 1 and "'gone' names a verb the parser no longer has" in found[0]


def test_an_exempted_verb_that_gained_an_action_is_found():
    found = _owner_found(_cli(), exempt={"restart": "no button yet, see #2138"})
    assert len(found) == 1 and "has an Action and is also exempted" in found[0]


def test_an_action_spelling_a_group_or_no_verb_is_found():
    found = _owner_found(_cli(), argvs=(("restart", "{}"), ("hold", "gpu"), ("hold",)))
    assert len(found) == 1 and "'hold', which is not a leaf verb" in found[0]


def test_an_exemption_without_a_one_line_reason_is_found():
    assert len(_owner_found(_cli("wipe"), exempt={"wipe": ""})) == 1


def test_every_owner_verb_of_the_real_parser_is_a_status_page_action_or_a_listed_exemption():
    from harness import owner_actions
    from harness.cli import build_parser
    paths = owner_verbs.verb_paths(build_parser())
    bound = owner_verbs.bound([a.argv for a in owner_actions.ACTIONS], paths)
    found = owner_verbs.check(paths, bound, owner_verbs.OWNER_EXEMPT, owner_verbs.NOT_OWNER)
    assert not found, "\n".join(found)
