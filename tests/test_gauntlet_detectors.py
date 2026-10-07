"""Tier-2 trigger detectors: each hit is bound to a test, waived with a reason, or in the shrinking backlog (#492 B)."""

import json
import re
from pathlib import Path

import pytest

from tests.gauntlet import classes, core, detectors

REPO = Path(__file__).resolve().parent.parent


def sites(fn, files):
    return sorted({h.site for h in fn(detectors.parse(files))})


def quiet_then_fires(fn, innocent, bad):
    # Quiet on the innocent files, and firing once the bad file joins them: quiet for the right reason.
    assert sites(fn, innocent) == []
    assert sites(fn, {**innocent, **bad}) != []


def test_a_closed_table_with_a_fallback_lookup_is_found():
    src = ("FAMILY = {\"qwen\": 1, \"llama\": 2, \"gemma\": 3}\n"
           "def size(name):\n    return FAMILY.get(name, 0)\n")
    other = "from harness import t\ndef f(k):\n    return t.SPEC.get(k)\n"
    table = "SPEC = {\"a\": 1, \"b\": 2, \"c\": 3}\n"
    got = sites(detectors.closed_tables, {"harness/t.py": src + table, "harness/u.py": other})
    assert got == ["harness/t.py:FAMILY", "harness/t.py:SPEC"]


def test_a_closed_table_looked_up_by_a_constant_or_refusing_is_left_alone():
    innocent = {"harness/t.py": ("FAMILY = {\"qwen\": 1, \"llama\": 2, \"gemma\": 3}\n"
                                 "SMALL = {\"a\": 1}\nlower = {\"a\": 1, \"b\": 2, \"c\": 3}\n"
                                 "def f(k):\n    return FAMILY[k], FAMILY.get(\"qwen\", 0), SMALL.get(k, 0)\n"
                                 "def g(k, d):\n    return d.get(k, 0), lower.get(k)\n")}
    bad = {"harness/u.py": "from harness import t\ndef h(k):\n    return t.FAMILY.get(k, 9)\n"}
    quiet_then_fires(detectors.closed_tables, innocent, bad)


def test_state_read_from_the_newest_row_is_found():
    src = ("def latest(conn, n):\n"
           "    return conn.execute(\"SELECT v FROM verdicts WHERE n = ? \"\n"
           "                        \"ORDER BY id DESC LIMIT 1\", (n,)).fetchone()\n"
           "class S:\n    def last(self, c):\n"
           "        return c.execute(f\"SELECT * FROM {T} ORDER BY at DESC, id DESC\\n LIMIT 1\")\n")
    assert sites(detectors.latest_row_state, {"harness/s.py": src}) == ["harness/s.py:S.last", "harness/s.py:latest"]


def test_a_newest_row_query_that_is_not_state_is_left_alone():
    innocent = {"harness/s.py": ("Q = \"SELECT v FROM t ORDER BY id DESC LIMIT 10\"\n"
                                 "R = \"SELECT v FROM t ORDER BY id ASC LIMIT 1\"\n"
                                 "# ORDER BY id DESC LIMIT 1 in a comment\n")}
    bad = {"harness/x.py": "def f(c):\n    c.execute(\"select v from t order by id desc limit 1\")\n"}
    quiet_then_fires(detectors.latest_row_state, innocent, bad)


def test_a_guard_only_tests_call_is_found():
    files = {"harness/m.py": "def check_model(r):\n    return r\ndef ensure_dir(p):\n    return p\n",
             "harness/n.py": "from harness import m\nm.ensure_dir(1)\n",
             "tests/test_m.py": "from harness import m\ndef test_x():\n    m.check_model(1)\n"}
    assert sites(detectors.unreached_guards, files) == ["harness/m.py:check_model"]


def test_a_guard_production_calls_is_left_alone():
    innocent = {"harness/m.py": ("def check_model(r):\n    return r\n"
                                 "class C:\n    def guard_lane(self):\n        return 1\n"
                                 "def checker(x):\n    return x\n"),
                "harness/n.py": "from harness.m import check_model, C\ncheck_model(1)\nC().guard_lane()\n"}
    bad = {"harness/o.py": "def refuse_live(p):\n    return p\n"}
    quiet_then_fires(detectors.unreached_guards, innocent, bad)


def test_an_option_nothing_reads_is_found():
    files = {"harness/cli.py": ("def build(sub):\n    p = sub.add_parser(\"x\")\n"
                                "    p.add_argument(\"--dry-run\", action=\"store_true\")\n"
                                "    p.add_argument(\"--top\", type=int)\n"
                                "    p.add_argument(\"--seed\", dest=\"rng_seed\")\n"
                                "    p.add_argument(\"path\")\n"),
             "harness/commands/x.py": "def cmd_x(a):\n    return a.top\n"}
    assert sites(detectors.ignored_options, files) == [
        "harness/cli.py:--dry-run", "harness/cli.py:--seed", "harness/cli.py:path"]


def test_an_option_that_is_read_is_left_alone():
    innocent = {"harness/cli.py": ("def build(p):\n    p.add_argument(\"--dry-run\")\n"
                                   "    p.add_argument(\"-n\", \"--top\")\n    p.add_argument(\"--seed\", dest=\"rng\")\n"
                                   "    p.add_argument(\"names\", nargs=\"*\")\n"),
                "harness/commands/x.py": ("def cmd_x(a):\n    return a.dry_run, getattr(a, \"top\", 3), a.rng, "
                                          "a.names\n")}
    bad = {"harness/other.py": "def b(p):\n    p.add_argument(\"--never-read\")\n"}
    quiet_then_fires(detectors.ignored_options, innocent, bad)


def test_one_default_for_every_member_is_found():
    src = ("CTX = 8192\nTIMEOUT_S = 600\n"
           "def serve(model, ctx=CTX):\n    return ctx\n"
           "def run(model, *, wait=TIMEOUT_S):\n    return wait\n"
           "def load(repo, ceiling=ins.MEMORY_CEILING):\n    return ceiling\n")
    assert sites(detectors.member_defaults, {"harness/s.py": src}) == [
        "harness/s.py:load(ceiling)", "harness/s.py:run(wait)", "harness/s.py:serve(ctx)"]


def test_a_default_that_is_not_per_member_is_left_alone():
    innocent = {"harness/s.py": ("LIMIT = 10\nPORT = 8080\n"
                                 "def page(rows, limit=LIMIT, port=PORT, ctx=None, timeout=30):\n    return rows\n")}
    bad = {"harness/t.py": "BUDGET_GB = 22\ndef fits(m, budget=BUDGET_GB):\n    return m\n"}
    quiet_then_fires(detectors.member_defaults, innocent, bad)


def test_a_harness_failure_written_as_a_verdict_is_found():
    src = ("def screen(proc):\n    if proc.returncode != 0:\n        return Verdict(\"broken\", \"exited\")\n"
           "def inspect(repo):\n    try:\n        go(repo)\n    except OSError:\n"
           "        decide(repo, \"declined\")\n"
           "def verify(p):\n    return \"ok\" if p.returncode == 0 else \"broken\"\n")
    assert sites(detectors.harness_verdicts, {"harness/s.py": src}) == [
        "harness/s.py:inspect", "harness/s.py:screen", "harness/s.py:verify"]


def test_a_verdict_from_the_subject_s_own_output_is_left_alone():
    innocent = {"harness/s.py": ("def verdict(summary):\n    if not summary:\n        return \"broken\"\n"
                                 "    return \"works\"\n"
                                 "def run(p):\n    try:\n        go()\n    except OSError:\n"
                                 "        return \"queued\"\n"
                                 "REJECTIONS = (\"broken\", \"declined\")\n")}
    bad = {"harness/t.py": ("def run(p):\n    try:\n        go()\n    except TimeoutError:\n"
                            "        return \"broken\"\n")}
    quiet_then_fires(detectors.harness_verdicts, innocent, bad)


def test_one_list_written_in_two_modules_is_found():
    files = {"harness/a.py": "TERMINAL = (\"measured\", \"broken\", \"declined\")\n",
             "harness/b.py": "DONE = {\"declined\", \"broken\", \"measured\"}\n",
             "harness/c.py": "OTHER = (\"measured\", \"broken\")\n"}
    assert sites(detectors.duplicated_literals, files) == ["harness/a.py:TERMINAL", "harness/b.py:DONE"]


def test_one_list_written_once_is_left_alone():
    innocent = {"harness/a.py": "TERMINAL = (\"measured\", \"broken\", \"declined\")\nONE = (\"x\",)\n",
                "harness/b.py": ("from harness.a import TERMINAL\nDONE = TERMINAL\nONE = (\"x\",)\n"
                                 "def f():\n    local = (\"measured\", \"broken\", \"declined\")\n    return local\n"),
                "tests/test_a.py": "WANT = (\"measured\", \"broken\", \"declined\")\n"}
    bad = {"evals/c.py": "STATES = [\"declined\", \"measured\", \"broken\"]\n"}
    quiet_then_fires(detectors.duplicated_literals, innocent, bad)


def test_an_environment_variable_read_is_a_seam():
    files = {"harness/a.py": ("import os\nH = os.environ.get(\"LOCALHARNESS_HOME\")\n"
                              "K = os.environ[\"SOHOT_KEY\"]\nP = os.getenv(\"HOME\")\n"),
             "harness/b.py": "import os\nH = os.environ.get(\"LOCALHARNESS_HOME\", \"\")\n"}
    assert sites(detectors.env_seams, files) == ["env:LOCALHARNESS_HOME", "env:SOHOT_KEY"]


def test_a_common_or_written_variable_is_not_a_seam():
    innocent = {"harness/a.py": ("import os\nos.environ[\"X_SET\"] = \"1\"\nP = os.getenv(\"PATH\")\n"
                                 "U = os.environ.get(\"USER\")\nT = os.environ.get(name)\n"),
                "tests/test_a.py": "import os\nZ = os.environ.get(\"ONLY_TESTS\")\n"}
    bad = {"harness/b.py": "import os\nV = os.environ.get(\"SOHOT_NEW\")\n"}
    quiet_then_fires(detectors.env_seams, innocent, bad)


def test_a_marker_binds_a_test_to_a_class_and_a_site():
    src = ("import pytest\n"
           "@pytest.mark.gauntlet(\"a-closed-table-fronting-an-open-set\", site=\"harness/t.py:FAMILY\")\n"
           "def test_a():\n    pass\n"
           "@pytest.mark.slow\n@pytest.mark.gauntlet(\"one-question-two-answers\", site=\"harness/a.py:X\")\n"
           "def test_b():\n    pass\n"
           "class TestC:\n    @pytest.mark.gauntlet(\"x\", site=\"harness/c.py:Y\")\n    def test_c(self):\n        pass\n")
    got = detectors.bindings({"tests/test_t.py": src})
    assert got == {("a-closed-table-fronting-an-open-set", "harness/t.py:FAMILY"): ["tests/test_t.py::test_a"],
                   ("one-question-two-answers", "harness/a.py:X"): ["tests/test_t.py::test_b"],
                   ("x", "harness/c.py:Y"): ["tests/test_t.py::TestC::test_c"]}


def test_a_marker_with_no_site_or_outside_tests_binds_nothing():
    src = ("import pytest\n@pytest.mark.gauntlet(\"x\")\ndef test_a():\n    pass\n"
           "@pytest.mark.gauntlet(\"x\", site=name)\ndef test_b():\n    pass\n")
    assert detectors.bindings({"tests/test_t.py": src}) == {}
    good = "import pytest\n@pytest.mark.gauntlet(\"x\", site=\"a:b\")\ndef test_a():\n    pass\n"
    assert detectors.bindings({"harness/t.py": good}) == {}
    assert detectors.bindings({"tests/test_t.py": good}) != {}


def test_the_ledger_splits_hits_into_bound_waived_and_unbound():
    hits = {"c": [detectors.Hit("a:X", 1, ""), detectors.Hit("a:Y", 2, ""), detectors.Hit("a:Z", 3, "")]}
    index = {"c": {"detector": "d", "waivers": {"a:Y": "reason"}}}
    led = detectors.ledger(hits, {("c", "a:X"): ["t::x"], ("c", "a:gone"): ["t::y"]}, index)
    assert led["c"]["bound"] == ["a:X"]
    assert led["c"]["waived"] == ["a:Y"]
    assert led["c"]["unbound"] == ["a:Z"]
    assert led["c"]["stale_bindings"] == ["a:gone"]
    assert led["c"]["stale_waivers"] == []


def test_the_marker_is_registered():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"gauntlet\(class_id, site\):', text)


def test_every_detector_named_in_the_index_exists_and_every_detector_is_named():
    named = {e["detector"] for e in classes.INDEX.values() if "detector" in e}
    assert named == set(detectors.DETECTORS)


def test_the_registry_shape_of_waivers_and_review_is_checked():
    index = {"c": {"instances": [{"issue": 1}], "scanners": [], "waivers": {"a:b": " "},
                   "review": "([unclosed"}}
    snap = [{"id": "c", "tier": 2}]
    got = core.problems(index, {}, {}, snap, {1: {"title": "", "created": ""}}, REPO)
    assert any("waiver a:b has no reason" in p for p in got)
    assert any("review heuristic does not compile" in p for p in got)


# The whole tree: computed once, shared by the tests below.
@pytest.fixture(scope="module")
def tree_ledger():
    trees = detectors.parse(detectors.sources(REPO))
    hits = detectors.run(trees, classes.INDEX)
    marks = detectors.bindings(detectors.sources(REPO, tests=True))
    return detectors.ledger(hits, marks, classes.INDEX), marks


def _backlog():
    return json.loads(detectors.BACKLOG_FILE.read_text(encoding="utf-8"))


def test_no_new_code_trips_a_detector_without_a_bound_test(tree_ledger):
    led, _ = tree_ledger
    backlog = _backlog()
    new = [f"{cid}: {s}" for cid, row in led.items() for s in row["unbound"] if s not in backlog.get(cid, [])]
    assert not new, ("these sites trip a gauntlet trigger: bind a test with "
                     "@pytest.mark.gauntlet(class_id, site=...) or waive it in classes.INDEX with a reason:\n  "
                     + "\n  ".join(new))


def test_the_backlog_only_shrinks(tree_ledger):
    led, _ = tree_ledger
    backlog = _backlog()
    gone = [f"{cid}: {s}" for cid, rows in backlog.items() for s in rows
            if s not in led.get(cid, {}).get("unbound", [])]
    assert not gone, "bound, waived or gone: remove from tests/gauntlet/backlog.json:\n  " + "\n  ".join(gone)
    total = sum(len(v) for v in backlog.values())
    assert total <= BACKLOG_PIN, f"the backlog grew to {total}, pinned at {BACKLOG_PIN}"
    assert total == BACKLOG_PIN, f"the backlog shrank to {total}: lower BACKLOG_PIN to {total}"


def test_no_binding_or_waiver_names_a_site_no_detector_finds(tree_ledger):
    led, marks = tree_ledger
    stale = [f"{cid}: binding {s}" for cid, row in led.items() for s in row["stale_bindings"]]
    stale += [f"{cid}: waiver {s}" for cid, row in led.items() for s in row["stale_waivers"]]
    detected = {cid for cid, e in classes.INDEX.items() if "detector" in e}
    stale += [f"{cid}: binding {s} for a class with no detector" for cid, s in marks if cid not in detected]
    assert not stale, "\n  ".join(stale)


# Unbound hits pinned when the detectors landed; lower it as the backlog is bound.
BACKLOG_PIN = 65


def test_every_detector_s_hits_are_reported_per_class(tree_ledger):
    led, _ = tree_ledger
    for cid in led:
        assert cid in classes.INDEX
    assert {cid for cid, e in classes.INDEX.items() if "detector" in e} == set(led)


def test_the_agent_lane_s_deliberately_broken_case_repos_are_not_production():
    got = detectors.sources(REPO)
    assert "harness/cli.py" in got
    assert not [rel for rel in got if rel.startswith("evals/cases/")]


def test_a_marker_may_name_its_class_through_a_module_constant():
    src = ("import pytest\nCLOSED = \"a-closed-table-fronting-an-open-set\"\n"
           "@pytest.mark.gauntlet(CLOSED, site=\"harness/t.py:FAMILY\")\ndef test_a():\n    pass\n"
           "@pytest.mark.gauntlet(UNKNOWN, site=\"harness/t.py:X\")\ndef test_b():\n    pass\n")
    assert detectors.bindings({"tests/test_t.py": src}) == {
        ("a-closed-table-fronting-an-open-set", "harness/t.py:FAMILY"): ["tests/test_t.py::test_a"]}
