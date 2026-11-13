"""soh scaffold writes new code with its registrations; make precheck names each missing one and the line that adds it (#1697)."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import knobs, scaffold
from harness import inventory_weight as iw
from tests.gauntlet import precheck
from tests.test_knob_merge import git

REPO = Path(__file__).resolve().parent.parent


def tree(root: Path, files: dict) -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    if not (root / ".git").exists():
        git(root, "init", "-q", "-b", "main")
    return root


def text_of(problems) -> str:
    return precheck.render(problems)


def test_an_unregistered_gating_constant_is_named_with_its_not_gating_and_knob_lines(tmp_path):
    root = tree(tmp_path, {"harness/fixture.py": "NAME = 'x'\n"})
    assert precheck.knob_sites(root) == []
    tree(root, {"harness/fixture.py": "WAIT_S = 5.0\n"})
    got = text_of(precheck.knob_sites(root))
    assert "harness/fixture.py:WAIT_S gates an outcome" in got
    assert 'harness/knobs/fixture.py NOT_GATING:\n        "harness/fixture.py:WAIT_S": "<why it gates no outcome>",' in got
    assert '_k("fixture_wait_s", ["harness/fixture.py:WAIT_S"], [<value now>, <other values>],' in got


def test_a_backlog_line_added_on_a_branch_or_left_behind_is_named(tmp_path):
    backlog = "tests/gauntlet/knob_backlog/harness.txt"
    root = tree(tmp_path, {"harness/a.py": "MAX_A = 3\n", backlog: "harness/a.py:MAX_A\nharness/b.py:MAX_B\n"})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert [p.subject for p in precheck.knob_backlog_lines(root)] == ["harness/b.py:MAX_B is registered or gone"]
    tree(root, {"harness/c.py": "MAX_C = 3\n", backlog: "harness/a.py:MAX_A\nharness/c.py:MAX_C\n"})
    got = text_of(precheck.knob_backlog_lines(root))
    assert "harness/c.py:MAX_C joined the backlog" in got
    assert f"delete this line from {backlog}: harness/c.py:MAX_C" in got
    assert '"harness/c.py:MAX_C": "<why it gates no outcome>",' in got


def test_a_not_gating_entry_the_inventory_no_longer_finds_is_named(tmp_path, monkeypatch):
    root = tree(tmp_path, {"harness/fixture.py": "WAIT_S = 5.0\n"})
    monkeypatch.setattr(knobs, "NOT_GATING", {"harness/fixture.py:WAIT_S": "paces", "harness/fixture.py:GONE_S": "x"})
    got = precheck.knob_entries(root)
    assert [p.subject for p in got] == ["harness/fixture.py:GONE_S is no longer found"]
    assert 'NOT_GATING: "harness/fixture.py:GONE_S"' in text_of(got)


def test_a_registered_limit_with_no_cut_is_named_with_its_cut_and_never_cuts_lines(tmp_path, monkeypatch):
    root = tree(tmp_path, {"harness/fixture.py": "WAIT_S = 5.0\n"})
    monkeypatch.setattr(knobs, "KNOBS", {"fixture_wait": knobs.Knob("fixture_wait", ("harness/fixture.py:WAIT_S",), (5.0,))})
    monkeypatch.setattr(knobs, "NOT_GATING", {})
    monkeypatch.setattr(knobs, "NEVER_CUTS", {})
    got = text_of(precheck.limit_traces(root))
    assert "harness/fixture.py:WAIT_S records no cut when it binds" in got
    assert 'with cuts.timeout("fixture_wait", what):' in got
    assert 'NEVER_CUTS:\n        "harness/fixture.py:WAIT_S": "<why it only paces work and never cuts any>",' in got
    tree(root, {"harness/fixture.py": "from harness import cuts\nWAIT_S = 5.0\n"
                                      "def f():\n    with cuts.timeout('fixture_wait', 'x'):\n        pass\n"})
    assert precheck.limit_traces(root) == []


def test_a_module_in_no_capability_or_over_budget_is_named_with_its_line(tmp_path):
    caps = ("trees: [harness]\ncapabilities:\n  - name: thing\n    summary: A thing.\n    spec: pending\n"
            "    modules:\n      - harness/thing.py\n      - harness/big.py\n")
    root = tree(tmp_path, {"openspec/capabilities.yaml": caps, "harness/thing.py": "", "harness/big.py": "x = 1\n" * 1501,
                           "tests/test_module_layout.py": "BUDGET = 1500\nOVER_BUDGET: dict = {}\n"})
    assert [p.subject for p in precheck.module_layout(root)] == ["harness/big.py is 1501 lines, over the 1500 budget"]
    tree(root, {"harness/commands/thing.py": ""})
    got = text_of(precheck.module_layout(root))
    assert "harness/commands/thing.py: in no capability" in got
    assert "add under openspec/capabilities.yaml 'thing' modules:\n          - harness/commands/thing.py" in got
    assert '"harness/big.py": "<why it is not split yet>",' in got


def test_a_launchd_unit_with_no_declared_output_is_named_with_its_unit_outputs_line(tmp_path):
    units = " ".join(iw.UNIT_OUTPUTS)
    root = tree(tmp_path, {"scripts/launchd.sh": f'SERVICES="{units}"\n'})
    assert precheck.unit_outputs(root) == []
    tree(root, {"scripts/launchd.sh": f'SERVICES="{units} nightly served"\n',
                "scripts/serve-served.sh": 'PORT="${SERVED_PORT:-8099}"\n'})
    got = text_of(precheck.unit_outputs(root))
    assert 'UNIT_OUTPUTS:\n        "nightly": ("<store table it writes>", "<its time column>", "", ("nightly",)),' in got
    assert '"served": ("gateway_requests", "at", PORT, ()),' in got


def test_a_test_file_importing_a_mutated_module_is_named_with_its_left_out_line(tmp_path):
    root = tree(tmp_path, {"tests/test_new_1697.py": "from harness import reasons\n"})
    got = text_of(precheck.mutation_tests(root))
    assert 'LEFT_OUT["harness/reasons.py"]: "test_new_1697.py",' in got


def test_an_unhomed_probe_is_named_with_its_eval_waived_line(tmp_path):
    root = tree(tmp_path, {"harness/x.py": "import argparse\nap = argparse.ArgumentParser()\n"
                                           "sub = ap.add_subparsers()\nb = sub.add_parser('probe')\n"})
    got = text_of(precheck.eval_homes(root))
    assert 'EVAL_WAIVED:\n        "harness/x.py sub probe": "<why its rows never pass for real work>",' in got


def test_a_detector_hit_with_no_bound_test_is_named_with_its_marker(tmp_path):
    root = tree(tmp_path, {"harness/u.py": 'def f(b):\n    return b != "http://localhost:4000"\n',
                           "tests/gauntlet/backlog.txt": ""})
    got = text_of(precheck.detector_bindings(root))
    assert '@pytest.mark.gauntlet("identity-by-name-not-by-content", site="harness/u.py:f")' in got
    tree(root, {"tests/test_u.py": 'import pytest\n@pytest.mark.gauntlet("identity-by-name-not-by-content", '
                                   'site="harness/u.py:f")\ndef test_f():\n    pass\n'})
    assert precheck.detector_bindings(root) == []


def test_precheck_runs_only_its_cheap_detectors_and_counts_no_skipped_class_row_as_gone(tmp_path, monkeypatch):
    """#1832: precheck runs registry.PRECHECK_DETECTORS, never the whole v0.2.2 set; make check runs the rest."""
    from gauntlet import detectors

    from tests.gauntlet import classes, registry
    ran = []
    monkeypatch.setattr(detectors, "DETECTORS", {
        name: (lambda name: lambda *a, **kw: ran.append(name) or [])(name) for name in detectors.DETECTORS})
    skipped = next(cid for cid, e in classes.INDEX.items()
                   if detectors.names(e) and not set(detectors.names(e)) <= registry.PRECHECK_DETECTORS)
    root = tree(tmp_path, {"harness/u.py": "X = 1\n", "tests/gauntlet/backlog.txt": f"{skipped} harness/u.py:f\n"})
    assert precheck.detector_bindings(root) == []
    named = {n for e in classes.INDEX.values() for n in detectors.names(e)}
    assert set(ran) == registry.PRECHECK_DETECTORS and registry.PRECHECK_DETECTORS < named


def test_a_gauntlet_backlog_row_added_after_the_merge_base_is_named(tmp_path):
    from tests.gauntlet import registry
    snap = registry.REGISTRY.snapshot_file.relative_to(registry.REPO).as_posix()
    cid = "identity-by-name-not-by-content"
    root = tree(tmp_path, {"harness/u.py": "X = 1\n", "tests/gauntlet/backlog.txt": "",
                           snap: registry.REGISTRY.snapshot_file.read_text(encoding="utf-8")})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    assert precheck.detector_bindings(root) == []
    tree(root, {"tests/gauntlet/backlog.txt": f"{cid} harness/u.py:f\n"})
    got = text_of(precheck.detector_bindings(root))
    assert f"{cid} harness/u.py:f joined the backlog after the merge base with origin/main" in got


def test_an_unregistered_move_table_is_named_with_its_move_table_line(tmp_path):
    root = tree(tmp_path, {"harness/thing_state.py": 'A, B = "a", "b"\nMOVES = {(A, B), (B, A)}\n'})
    got = text_of(precheck.move_tables(root))
    assert 'MoveTable("harness/thing_state.py:MOVES", <module>.MOVES' in got
    assert precheck.move_tables(REPO) == []


def test_a_new_mode_flag_is_named_with_its_not_run_line(tmp_path):
    import argparse
    p = argparse.ArgumentParser()
    verb = p.add_subparsers().add_parser("verb")
    verb.add_argument("--wet", action="store_true")
    verb.add_argument("--store", action="store_true")
    pins = 'FLAGS = ("--store",)\nREAD_ONLY = {"other --x": ([["other", "--x", S]], 0)}\nMODIFIERS = {"other --y"}\n'
    root = tree(tmp_path, {"tests/test_lent_store_1426.py": pins + "NOT_RUN = {}\n"})
    got = text_of(precheck.mode_flags(root, p))
    assert 'NOT_RUN:\n        "verb --wet": "<why its mode is not run here>",' in got and "--store" not in got
    tree(root, {"tests/test_lent_store_1426.py": pins + 'NOT_RUN = {"verb --wet": "writes"}\n'})
    assert precheck.mode_flags(root, p) == []


def test_a_knob_lands_in_name_order_and_leaves_the_backlog(tmp_path):
    area = 'from harness.knobs.base import _k\n\nKNOBS = [\n    _k("a_one", ["harness/a.py:A_S"], [1.0]),\n' \
           '    _k("c_three", ["harness/a.py:C_S"], [3.0]),\n]\n'
    root = tree(tmp_path, {"harness/knobs/fix.py": area, "tests/gauntlet/knob_backlog/harness.txt": "harness/a.py:B_S\n"})
    done = []
    scaffold.add_knob(root, "fix", "b_two", "harness/a.py:B_S", [2.0], "what it limits (#1697)", "s", "#1697", done)
    text = (root / "harness/knobs/fix.py").read_text(encoding="utf-8")
    assert text.index('"a_one"') < text.index('"b_two"') < text.index('"c_three"')
    assert not (root / "tests/gauntlet/knob_backlog/harness.txt").exists(), "an emptied backlog file is removed"
    assert done == ["harness/knobs/fix.py", "tests/gauntlet/knob_backlog/harness.txt"]
    scaffold.add_why(root, "fix", "NOT_GATING", "harness/a.py:D_S", "paces (#1697)", "#1697", done)
    scaffold.add_why(root, "new_area", "NEVER_CUTS", "harness/a.py:E_S", "paces (#1697)", "#1697", done)
    ns = {}
    exec((root / "harness/knobs/new_area.py").read_text(encoding="utf-8"), ns)
    assert ns["KNOBS"] == [] and ns["NEVER_CUTS"] == {"harness/a.py:E_S": "paces (#1697)"}
    with pytest.raises(scaffold.ScaffoldError, match="already"):
        scaffold.add_why(root, "fix", "NOT_GATING", "harness/a.py:D_S", "again", "#1697", done)


def _copy(dst: Path) -> Path:
    """The checkout's files without .git and without the case tree's data, which no ratchet reads."""
    names = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=REPO, capture_output=True,
                           text=True, check=True).stdout.splitlines()
    for rel in names:
        src = REPO / rel
        if not src.is_file() or (rel.startswith("evals/cases/") and not rel.endswith(".py")):
            continue
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / rel)
    git(dst, "init", "-q", "-b", "main")
    return dst


def _precheck(root: Path, *only: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "tests.gauntlet.precheck", *(f"--only={o}" for o in only)], cwd=root,
                          capture_output=True, text=True, encoding="utf-8")


def test_precheck_only_runs_the_ratchets_it_names(capsys):
    assert precheck.main(["--only", "module_layout", "--only", "mode_flags"]) == 0
    assert "in 2 registration ratchets" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        precheck.main(["--only", "no_such_ratchet"])


def test_code_the_scaffold_writes_passes_every_registration_ratchet_unchanged(tmp_path):
    root = _copy(tmp_path / "repo")
    from harness import cli
    assert cli.main(["scaffold", "--root", str(root), "--issue", "1697", "module", "harness/fixture_1697.py",
                     "A module the scaffold test writes", "--capability", "repo-hygiene", "--command"]) == 0
    assert cli.main(["scaffold", "--root", str(root), "--issue", "1697", "timeout", "harness/fixture_1697.py",
                     "FETCH_TIMEOUT_S", "30", "--why", "a fixture nothing calls"]) == 0
    assert cli.main(["scaffold", "--root", str(root), "--issue", "1697", "unit", "fixture-1697", "soh fixture-1697",
                     "A unit the scaffold test writes", "--hours", "5", "--table", "jobs", "--time-col", "finished_at"]) == 0
    got = _precheck(root)
    assert str(root / "harness") in subprocess.run([sys.executable, "-c", "import harness; print(harness.__file__)"],
                                               cwd=root, capture_output=True, text=True).stdout, "the copy's code ran"
    assert got.returncode == 0, got.stdout[-4000:] + got.stderr[-2000:]
    caps = (root / scaffold.CAPABILITIES).read_text(encoding="utf-8")
    (root / scaffold.CAPABILITIES).write_text(caps.replace("      - harness/fixture_1697.py\n", ""), encoding="utf-8")
    red = _precheck(root, "module_layout")
    assert red.returncode == 1 and "          - harness/fixture_1697.py" in red.stdout, red.stdout[-4000:]


def test_the_scaffold_refuses_what_no_ratchet_would_see(tmp_path):
    root = tree(tmp_path, {"harness/m.py": '"""m."""\nimport os\n'})
    with pytest.raises(scaffold.ScaffoldError, match="no inventory site"):
        scaffold.timeout(root, "harness/m.py", "PERIOD", 3, why="x")
    with pytest.raises(scaffold.ScaffoldError, match="exactly one"):
        scaffold.timeout(root, "harness/m.py", "WAIT_S", 3)
    with pytest.raises(scaffold.ScaffoldError, match="exists"):
        scaffold.module(root, "harness/m.py", "again", capability="x")
    with pytest.raises(scaffold.ScaffoldError, match="hours"):
        scaffold.unit(root, "u", "25", "soh x", "u")
    assert scaffold.unit_line("u", "t", "at", "", ("a", "b")) == '    "u": ("t", "at", "", ("a", "b",)),'
