"""A pull request runs the tests a recorded coverage map says execute its change; the rest go by import. #1571."""
import functools
import io
import json
import os
import subprocess
import sys
import types
import zipfile
from pathlib import Path

import pytest
import yaml

from harness import knob_backlog, knobs, limit_trace
from tests import conftest
from tests.gauntlet import covmap, scope

REPO = Path(__file__).resolve().parent.parent

LEAF = ("LIMIT = 5\n"
        "\n"
        "\n"
        "def f():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def g():\n"
        "    return LIMIT\n")
TEXTS = {
    "harness/__init__.py": "",
    "harness/leaf.py": LEAF,
    "harness/middle.py": "from harness import leaf\n\n\ndef calls_f():\n    return leaf.f()\n",
    "harness/runs.py": "import subprocess\n\n\ndef go():\n    subprocess.run(['python', '-m', 'harness.leaf'])\n",
    "tests/test_f.py": "from harness import middle\n\n\ndef test_f():\n    assert middle.calls_f() == 1\n",
    "tests/test_g.py": "from harness import leaf\n\n\ndef test_g():\n    assert leaf.g() == 5\n",
    "tests/test_reads_limit.py": "from harness import leaf\n\n\ndef test_x():\n    assert leaf.LIMIT\n",
    "tests/test_new.py": "from harness import leaf\n",
    "tests/test_spawns.py": "import subprocess\nsubprocess.run(['python', '-m', 'harness.leaf'])\n",
    "tests/test_go.py": "from harness import runs\n\n\ndef test_go():\n    runs.go()\n",
    "tests/test_knobs.py": "",
}
TESTS = {p for p in TEXTS if scope.is_test(p)}
MAP = {"version": covmap.VERSION, "commit": "abc",
       "tests": ["tests/test_f.py", "tests/test_g.py", "tests/test_reads_limit.py", "tests/test_spawns.py",
                 "tests/test_go.py", "tests/test_knobs.py"],
       "files": {"harness/leaf.py": {"f": {"f": [0], "g": [1]}, "import": []},
                 "harness/middle.py": {"f": {"calls_f": [0]}, "import": []},
                 "harness/runs.py": {"f": {"go": [4]}, "import": []},
                 "harness/__init__.py": {"f": {}, "import": []}}}


def _edit(text, old, new):
    after = text.replace(old, new)
    line = text[:text.index(old)].count("\n") + 1
    return {"harness/leaf.py": (text, after, [(line, 1, line, 1)])}


def _select(diff, cmap=MAP, texts=TEXTS, stale=frozenset()):
    return scope.select(list(diff), texts, TESTS, (), None, cmap, diff, stale)


def test_a_body_change_selects_the_tests_that_ran_that_function_not_every_importer():
    chosen, why = _select(_edit(LEAF, "return 1", "return 2"))
    assert "tests/test_f.py" in chosen and "tests/test_g.py" not in chosen
    assert "tests/test_reads_limit.py" not in chosen
    assert any("harness/leaf.py:" in w and "coverage map" in w for w in why)
    graph, _ = scope.select(["harness/leaf.py"], TEXTS, TESTS)
    assert "tests/test_g.py" in graph


def test_a_constant_change_reaches_the_functions_and_tests_that_read_it():
    chosen, _ = _select(_edit(LEAF, "LIMIT = 5", "LIMIT = 6"))
    assert {"tests/test_g.py", "tests/test_reads_limit.py"} <= set(chosen)
    assert "tests/test_f.py" not in chosen


def test_a_name_is_followed_only_where_a_file_reads_it_from_the_changed_module_and_never_through_conftest():
    texts = {**TEXTS,
             "harness/other.py": "LIMIT = 9\n",
             "tests/test_other_limit.py": "from harness import leaf, other\n\n\ndef test_x():\n    assert other.LIMIT\n",
             "tests/test_from_import.py": "from harness.leaf import LIMIT as CAP\n\n\ndef test_x():\n    assert CAP\n",
             "tests/conftest.py": "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef pin(monkeypatch):\n"
                                 "    monkeypatch.setattr('harness.leaf.LIMIT', 5)\n    monkeypatch.setattr('harness.leaf.f', 1)\n"}
    cmap = json.loads(json.dumps(MAP))
    cmap["tests"] += ["tests/test_other_limit.py", "tests/test_from_import.py"]
    cmap["files"]["tests/conftest.py"] = {"f": {"pin": list(range(len(cmap["tests"])))}, "import": []}
    tests = {p for p in texts if scope.is_test(p)}
    diff = _edit(LEAF, "LIMIT = 5", "LIMIT = 6")
    chosen, _ = scope.select(list(diff), texts, tests, (), None, cmap, diff)
    assert {"tests/test_from_import.py", "tests/test_reads_limit.py"} <= set(chosen)
    assert "tests/test_other_limit.py" not in chosen and "tests/test_f.py" not in chosen
    diff = _edit(LEAF, "return 1", "return 2")
    chosen, _ = scope.select(list(diff), texts, tests, (), None, cmap, diff)
    assert "tests/test_g.py" not in chosen


def test_a_module_level_loop_variable_is_not_a_name_users_read_but_what_the_loop_fills_is():
    text = "TABLE = {}\nfor name in ('a', 'b'):\n    TABLE[name] = 1\nWAYS = [w for w in TABLE]\nTABLE.update(c=1)\n"
    t = covmap.touched(text, text.replace("'b'", "'c'").replace("for w in", "for w  in"), [(2, 1, 2, 1), (4, 1, 4, 1)])
    assert t.names == {"TABLE", "WAYS"} and not t.opaque
    t = covmap.touched(text, text.replace("c=1", "c=2"), [(5, 1, 5, 1)])
    assert t.names == {"TABLE"} and not t.opaque
    t = covmap.touched("register(1)\n", "register(2)\n", [(1, 1, 1, 1)])
    assert t.opaque


def test_a_module_level_statement_that_binds_nothing_falls_back_to_the_import_graph():
    text = LEAF + "print(LIMIT)\n"
    chosen, why = _select(_edit(text, "print(LIMIT)", "print(LIMIT, 1)"), texts={**TEXTS, "harness/leaf.py": text})
    assert {"tests/test_f.py", "tests/test_g.py", "tests/test_new.py"} <= set(chosen)
    assert any("import graph" in w for w in why)


def test_a_function_that_runs_at_import_falls_back_to_the_import_graph():
    cmap = json.loads(json.dumps(MAP))
    cmap["files"]["harness/leaf.py"]["import"] = ["f"]
    chosen, why = _select(_edit(LEAF, "return 1", "return 2"), cmap=cmap)
    assert "tests/test_g.py" in chosen and any("f runs at import" in w for w in why)


def test_a_test_file_the_map_never_saw_is_chosen_by_import():
    chosen, _ = _select(_edit(LEAF, "return 1", "return 2"))
    assert "tests/test_new.py" in chosen


def test_a_subprocess_naming_the_module_is_chosen_though_coverage_cannot_see_it():
    chosen, _ = _select(_edit(LEAF, "return 1", "return 2"))
    assert {"tests/test_spawns.py", "tests/test_go.py"} <= set(chosen)


def test_a_file_changed_on_main_since_the_map_is_traced_by_import_and_its_callers_tests_are_kept():
    chosen, why = _select(_edit(LEAF, "return 1", "return 2"), stale=frozenset({"harness/leaf.py"}))
    assert "tests/test_g.py" in chosen and any("changed since the map" in w for w in why)
    texts = {**TEXTS, "harness/fresh.py": "from harness import leaf\n\n\ndef uses():\n    return leaf.f()\n",
             "tests/test_fresh.py": "from harness import fresh\n\n\ndef test_x():\n    assert fresh.uses()\n"}
    cmap = json.loads(json.dumps(MAP))
    cmap["tests"].append("tests/test_fresh.py")
    cmap["files"]["harness/fresh.py"] = {"f": {"uses": [len(cmap["tests"]) - 1]}, "import": []}
    diff = _edit(LEAF, "return 1", "return 2")
    tests = {p for p in texts if scope.is_test(p)}
    chosen, _ = scope.select(list(diff), texts, tests, (), None, cmap, diff, frozenset())
    assert "tests/test_fresh.py" not in chosen
    stale = frozenset({"harness/fresh.py", "tests/test_g.py"})
    chosen, _ = scope.select(list(diff), texts, tests, (), None, cmap, diff, stale)
    assert {"tests/test_fresh.py", "tests/test_g.py"} <= set(chosen)


def test_what_a_hunk_touches_is_read_from_both_sides():
    t = covmap.touched(LEAF, LEAF.replace("return 1", "return 2"), [(5, 1, 5, 1)])
    assert t.funcs == {"f"} and not t.names and not t.opaque
    new = "import os\n" + LEAF
    t = covmap.touched(LEAF, new, [(0, 0, 1, 1)])
    assert t.own == {"os"} and not t.names
    t = covmap.touched(LEAF, LEAF.replace("def g():", "def g(x=1):"), [(8, 1, 8, 1)])
    assert t.names == {"g"} and not t.funcs
    cls = "class C:\n    A = 1\n\n    def m(self):\n        return self.A\n"
    t = covmap.touched(cls, cls.replace("A = 1", "A = 2"), [(2, 1, 2, 1)])
    assert t.names == {"C"}
    t = covmap.touched(cls, cls.replace("return self.A", "return 0"), [(5, 1, 5, 1)])
    assert t.funcs == {"C.m"}
    main = 'X = 1\nif __name__ == "__main__":\n    print(X)\n'
    assert covmap.touched(main, main.replace("print(X)", "print(2)"), [(3, 1, 3, 1)]) == covmap.Touched(
        set(), set(), set(), False)


def test_unified_diff_hunks_parse_with_and_without_counts():
    diff = ("diff --git a/harness/x.py b/harness/x.py\n--- a/harness/x.py\n+++ b/harness/x.py\n"
            "@@ -3 +3 @@ def f():\n-a\n+b\n@@ -10,0 +11,2 @@\n+c\n+d\n"
            "diff --git a/y.md b/y.md\n@@ -1,2 +0,0 @@\n")
    assert covmap.hunks(diff) == {"harness/x.py": [(3, 1, 3, 1), (10, 0, 11, 2)], "y.md": [(1, 2, 0, 0)]}


PLANT = {
    "app/__init__.py": "",
    "app/p.py": "def changed():\n    return 1\n\n\ndef other():\n    return 2\n",
    "app/b.py": "from app import p\n\n\ndef via_b():\n    return p.changed()\n",
    "app/a.py": "from app import b\n\n\ndef via_a():\n    return b.via_b()\n",
    "app/reg.py": "def table():\n    return [1]\n\n\nTABLE = table()\n",
    "tests/__init__.py": "",
    "tests/test_far.py": "from app import a\n\n\ndef test_far():\n    assert a.via_a() == 1\n",
    "tests/test_near.py": "from app import p, reg\n\n\ndef test_near():\n    assert p.other() == 2 and reg.TABLE\n",
}


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    root = tmp_path_factory.mktemp("planted")
    for rel, text in PLANT.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV", "PYTEST", "SOHOT"))}
    env["COVERAGE_FILE"] = str(root / ".coverage")
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider",
                          "--cov=app", "--cov=tests", "--cov-context=test", "--cov-report=", "tests"],
                         cwd=root, env=env, capture_output=True, text=True, timeout=conftest.HANG_DUMP_S)
    assert "2 passed" in got.stdout, got.stdout[-2000:] + got.stderr[-2000:]
    return root, covmap.build(root / ".coverage", root, "planted")


def test_a_test_calling_a_changed_function_through_two_other_modules_is_selected(planted):
    root, cmap = planted
    assert cmap["files"]["app/p.py"]["f"]["changed"] == [cmap["tests"].index("tests/test_far.py")]
    assert "table" in cmap["files"]["app/reg.py"]["import"]
    tests = {"tests/test_far.py", "tests/test_near.py"}
    text = PLANT["app/p.py"]
    diff = {"app/p.py": (text, text.replace("return 1", "return 3"), [(2, 1, 2, 1)])}
    chosen, _ = scope.select(["app/p.py"], PLANT, tests, (), None, cmap, diff)
    assert chosen == ["tests/test_far.py"]
    diff = {"app/p.py": (text, text.replace("return 2", "return 3"), [(6, 1, 6, 1)])}
    chosen, _ = scope.select(["app/p.py"], PLANT, tests, (), None, cmap, diff)
    assert chosen == ["tests/test_near.py"]


def _git(root, *args, when="2026-11-01T00:00:00"):
    env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_a_map_is_used_only_when_its_commit_is_an_ancestor_and_recent(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-qm", "one")
    old = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "two", when="2026-11-02T00:00:00")
    near = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "b.py")
    _git(tmp_path, "commit", "-qm", "three", when="2026-11-09T00:00:00")
    head = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "checkout", "-qb", "side", old)
    (tmp_path / "c.py").write_text("z = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "c.py")
    _git(tmp_path, "commit", "-qm", "side")
    side = _git(tmp_path, "rev-parse", "HEAD")

    def m(commit):
        return {"version": covmap.VERSION, "commit": commit, "tests": [], "files": {}}
    assert covmap.unusable(None, head, tmp_path) == "no coverage map"
    assert "not in this clone" in covmap.unusable(m("f" * 40), head, tmp_path)
    assert "not an ancestor" in covmap.unusable(m(side), head, tmp_path)
    assert "days older" in covmap.unusable(m(near), head, tmp_path)
    assert covmap.unusable(m(old), near, tmp_path) == ""
    assert covmap.since(m(old), head, tmp_path) == {"a.py", "b.py"}
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**m(old), "version": covmap.VERSION + 1}), encoding="utf-8")
    assert covmap.load(bad) is None and covmap.load(tmp_path / "missing.json") is None


def test_the_diff_carries_both_sides_of_each_changed_python_file(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "a.py").write_text(LEAF, encoding="utf-8")
    (tmp_path / "b.md").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py", "b.md")
    _git(tmp_path, "commit", "-qm", "one")
    (tmp_path / "a.py").write_text(LEAF.replace("return 1", "return 2"), encoding="utf-8")
    (tmp_path / "b.md").write_text("y\n", encoding="utf-8")
    got = scope.diff_of(["a.py", "b.md"], "HEAD", root=tmp_path)
    assert got == {"a.py": (LEAF, LEAF.replace("return 1", "return 2"), [(5, 1, 5, 1)])}
    _git(tmp_path, "commit", "-qam", "two")
    assert scope.diff_of(["a.py"], "HEAD^", "HEAD", root=tmp_path) == got
    t = covmap.touched(*got["a.py"])
    assert t.funcs == {"f"}


def test_a_replay_with_a_map_weighs_each_prs_selection_by_its_diff():
    prs = [{"number": 7, "files": [{"path": "harness/leaf.py"}]}]
    secs = {"tests/test_f.py": 10.0, "tests/test_g.py": 30.0}
    (_, graph, all_), = scope.replay(prs, TEXTS, TESTS, (), secs)
    (_, chosen, part), = scope.replay(prs, TEXTS, TESTS, (), secs, MAP, {7: _edit(LEAF, "return 1", "return 2")})
    assert all_ == 1.0 and part == pytest.approx(0.25) and "tests/test_g.py" not in chosen
    assert scope.median([0.1, 0.5, 0.2, 1.0]) == pytest.approx(0.35) and scope.median([3.0]) == 3.0


ARTIFACTS = [
    {"id": 1, "name": "coverage-map", "expired": False, "created_at": "2026-11-05T06:00:00Z",
     "workflow_run": {"head_branch": "main", "head_sha": "old"}},
    {"id": 2, "name": "coverage-map", "expired": False, "created_at": "2026-11-07T06:00:00Z",
     "workflow_run": {"head_branch": "some-pr", "head_sha": "pr"}},
    {"id": 3, "name": "coverage-map", "expired": True, "created_at": "2026-11-08T06:00:00Z",
     "workflow_run": {"head_branch": "main", "head_sha": "gone"}},
    {"id": 4, "name": "coverage-map", "expired": False, "created_at": "2026-11-06T06:00:00Z",
     "workflow_run": {"head_branch": "main", "head_sha": "new"}},
    {"id": 5, "name": "junit-macos", "expired": False, "created_at": "2026-11-09T06:00:00Z",
     "workflow_run": {"head_branch": "main", "head_sha": "x"}},
]


def test_the_newest_unexpired_map_from_main_is_the_one_fetched(tmp_path):
    assert covmap.choose(ARTIFACTS)["id"] == 4
    assert covmap.choose(list(reversed(ARTIFACTS)))["id"] == 4
    assert covmap.choose(ARTIFACTS[1:3]) is None
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as z:
        z.writestr(covmap.FILE, '{"version": 1}')
    asked = []

    def gh(args, binary=False):
        asked.append(args[1])
        return blob.getvalue() if binary else json.dumps({"artifacts": ARTIFACTS})
    out = tmp_path / "map.json"
    assert covmap.fetch(out, "o/r", gh) == "new"
    assert asked == ["repos/o/r/actions/artifacts?name=coverage-map&per_page=100", "repos/o/r/actions/artifacts/4/zip"]
    assert out.read_text(encoding="utf-8") == '{"version": 1}'
    with pytest.raises(RuntimeError, match="no unexpired"):
        covmap.fetch(out, "o/r", lambda args, binary=False: json.dumps({"artifacts": []}))


def test_the_nightly_records_the_map_and_the_pr_run_fetches_it():
    jobs = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"]
    job = jobs["coverage-map"]
    assert "schedule" in job["if"] and "pull_request" not in job["if"]
    run = " ".join(s.get("run", "") for s in job["steps"])
    assert "--cov-context=test" in run and "tests.gauntlet.covmap build" in run
    assert all(f"--cov={p}" in run for p in ("harness", "evals", "gateway", "tests"))
    assert any(s.get("env", {}).get(covmap.ENV) for s in job["steps"])
    upload = next(s for s in job["steps"] if "upload-artifact" in s.get("uses", ""))
    assert upload["with"]["name"] == covmap.ARTIFACT and upload["with"]["path"] == covmap.FILE
    pick = next(s for s in jobs["check-macos"]["steps"] if s.get("name") == "Which tests this change can reach")
    assert "tests.gauntlet.covmap fetch" in pick["run"] and "--map" in pick["run"]
    assert "coverage-map" in jobs["report-nightly"]["needs"]


def test_a_missing_map_traces_by_import_and_still_writes_the_listing(tmp_path, capsys):
    out = tmp_path / "selected.txt"
    assert scope.main(["--base", "HEAD", "--files", "tests/test_covmap_1571.py", "--map", str(tmp_path / "none.json"),
                       "--out", str(out)]) == 0
    assert "coverage map: no coverage map; tracing by import" in capsys.readouterr().out
    assert "tests/test_covmap_1571.py" in out.read_text(encoding="utf-8").split()


def test_the_knob_scan_analyses_each_source_text_once_and_hands_out_copies():
    text, rel = "MAX_ITEMS = 5\n\n\ndef f(timeout=30):\n    return timeout\n", "harness/x_1571.py"
    before = knobs._sites_of.cache_info()
    first = knobs._sites(text, rel)
    first["harness/x_1571.py:planted"] = 1
    assert knobs._sites(text, rel) == {"harness/x_1571.py:MAX_ITEMS": 5, "harness/x_1571.py:f(timeout)": 30}
    after = knobs._sites_of.cache_info()
    assert (after.misses - before.misses, after.hits - before.hits) == (1, 1)
    assert knobs.gating(text.replace("5", "6"), rel) == ["harness/x_1571.py:MAX_ITEMS", "harness/x_1571.py:f(timeout)"]
    cut = "from harness import cuts\n\n\ndef f(n):\n    cuts.cut('max_items_1571', 1)\n    cuts.cut(n, 1)\n"
    before = limit_trace._names_in.cache_info()
    names = limit_trace.names_in(cut, rel)
    names.append(("planted", ""))
    assert limit_trace.names_in(cut, rel) == [("max_items_1571", "harness/x_1571.py:5")]
    unnamed = limit_trace.unnamed_in(cut, rel)
    unnamed.append("planted")
    assert limit_trace.unnamed_in(cut, rel) == ["harness/x_1571.py:6"]
    assert limit_trace._names_in.cache_info().hits - before.hits == 1
    quoted = "LIMIT_1571 = 3\n\n\ndef f():\n    return f'over {LIMIT_1571}'\n"
    before = knob_backlog._quotes.cache_info()
    got = knob_backlog.quotes(quoted, rel)
    got.append(None)
    assert [q.text for q in knob_backlog.quotes(quoted, rel)] == ["over {}"]
    assert knob_backlog._quotes.cache_info().hits - before.hits == 1


def test_the_tree_scans_parse_each_text_once_and_still_name_what_does_not_parse():
    from tests import layout_scan
    from tests.gauntlet import detectors, scanners
    text = "def f_1571():\n    return 1\n"
    before = scanners.tree.cache_info()
    first = detectors.parse({"a.py": text})["a.py"]
    assert scanners._parse(text, "b.py")[0] is first and scanners.tree.cache_info().misses - before.misses == 1
    assert scanners._parse("def (:\n", "c.py") == (None, ["c.py:1: does not parse, so it was not scanned"])
    assert detectors.parse({"c.py": "def (:\n"}) == {}
    mods = layout_scan.code_modules()
    mods["planted_1571"] = ""
    assert "planted_1571" not in layout_scan.code_modules() and "harness.knobs" in mods


def test_the_map_run_empties_every_function_cache_in_the_repos_modules(monkeypatch):
    mod = types.ModuleType("harness._covmap_probe_1571")

    @functools.cache
    def cached(x):
        return x

    class Holder:
        @functools.lru_cache(maxsize=None)
        def method(self):
            return 1
    mod.cached, mod.Holder = cached, Holder
    monkeypatch.setitem(sys.modules, mod.__name__, mod)
    cached(1)
    Holder().method()
    covmap.clear_caches()
    assert cached.cache_info().currsize == 0 and Holder.method.cache_info().currsize == 0
