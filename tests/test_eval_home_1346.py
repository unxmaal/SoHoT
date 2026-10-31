"""Evals and probes never write the live store: a scratch home, a refusal, or a cut that records nothing. #1346."""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from harness import cuts, paths, purpose
from harness import memory_store as ms
from tests.gauntlet import scanners

SITE = "harness/cuts.py:WRITE_WAIT_S"
REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def live(tmp_path, monkeypatch):
    """A home that stands in for the live one, with a migrated store, seen from a checkout that is not the deploy."""
    home = tmp_path / "live"
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    ms.connect().close()
    monkeypatch.setattr(paths, "DEFAULT_HOME", home)
    monkeypatch.delenv(paths.ENV_VAR)
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: tmp_path / "deploy")
    return home


def _cut_rows(db: Path) -> int:
    import sqlite3
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM limit_cuts").fetchone()[0]
    finally:
        c.close()


def test_a_cut_from_a_checkout_that_is_not_the_deploy_leaves_the_live_home_alone(live):
    cuts.cut(SITE, "probe", value=1, kept=1, dropped=1)
    assert _cut_rows(live / "discovery.db") == 0
    assert not (live / cuts.SPOOL).exists(), "a spooled row reaches the live store at the deploy's next flush"


def test_the_deploy_checkout_still_records_its_cuts_in_the_live_home(live, monkeypatch):
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: None)
    cuts.cut(SITE, "work", value=1, kept=1, dropped=1)
    assert _cut_rows(live / "discovery.db") == 1


def test_an_eval_with_no_home_named_runs_from_a_scratch_one_and_tags_its_requests(live, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    got = paths.eval_home(tmp_path / "scratch")
    assert got == (tmp_path / "scratch").resolve() == paths.home()
    assert os.environ[paths.ENV_VAR] == str(got)
    assert purpose.current() == purpose.EVAL
    tmp = paths.eval_home()
    assert tmp != live and not paths.is_live(tmp / "discovery.db")


def test_an_eval_pointed_at_the_live_home_is_refused_unless_told_to_write_it(live, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(live))
    with pytest.raises(paths.LiveHomeRefused):
        paths.eval_home()
    with pytest.raises(paths.LiveHomeRefused):
        paths.eval_home(live)
    assert paths.eval_home(live=True) == live.resolve()


def test_a_scratch_home_named_by_the_caller_is_kept(live, monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "mine"))
    assert paths.eval_home(tmp_path / "other") == (tmp_path / "mine").resolve()


def _cutting(*a, **k):
    cuts.cut(SITE, "a probe's own limit", value=0, kept=0, dropped=1)


def _sensitivity(monkeypatch):
    from harness import cli, probes
    monkeypatch.setattr(probes, "run", lambda names: _cutting() or [])
    monkeypatch.setattr(probes, "coverage", lambda: {"crowd": 0, "clones": 0})
    return cli.main(["sensitivity", "--json", sorted(probes.PROBES)[0]])


def _discover_control(monkeypatch):
    from harness import cli, judge
    monkeypatch.setattr(judge, "control_repeated", lambda **k: _cutting() or {})
    return cli.main(["discover", "--control", "--json"])


def _slot_probe(monkeypatch):
    from harness import slot_probe
    monkeypatch.setattr(slot_probe, "_get", lambda *a, **k: _cutting() or {"data": []})
    return slot_probe.main(["--router", "http://127.0.0.1:9"])


@pytest.mark.parametrize("entry", [_sensitivity, _discover_control, _slot_probe])
def test_a_probe_run_by_the_deploy_in_the_live_home_records_none_of_its_cuts(live, monkeypatch, entry):
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: None)
    before = (live / "discovery.db").read_bytes()
    assert entry(monkeypatch) == 0
    assert _cut_rows(live / "discovery.db") == 0
    assert not (live / cuts.SPOOL).exists()
    assert (live / "discovery.db").read_bytes() == before
    assert purpose.current() == purpose.EVAL


def test_an_eval_or_probe_entry_that_is_neither_homed_nor_waived_is_found():
    src = ("import argparse\nap = argparse.ArgumentParser()\nap.add_argument('--eval', default='')\n"
           "sub = ap.add_subparsers()\nb = sub.add_parser('probe')\nc = sub.add_parser('route-probe')\n"
           "ap.add_argument('action', choices=('import', 'control'))\nap.add_argument('--redo', action='store_true')\n")
    got = scanners.unhomed_evals(src, "harness/x.py", homed={}, waived={})
    assert [f.split(":")[1] for f in got] == ["3", "5", "6", "7", "8"]
    assert "'harness/x.py ap action=control'" in got[3]


def test_a_homed_or_waived_entry_and_an_ordinary_option_are_left_alone():
    src = ("ap.add_argument('--eval', default='')\nb = sub.add_parser('probe')\n"
           "ap.add_argument('--evaluate-at', default='')\nap.add_argument('--probe-timeout', type=float)\n"
           "ap.add_argument('--model')\nsub.add_parser('report')\nap.add_argument('kind', choices=('a', 'b'))\n")
    homed, waived = {"harness/x.py ap --eval": "harness/x.py"}, {"harness/x.py sub probe": "no store"}
    assert scanners.unhomed_evals(src, "harness/x.py", homed=homed, waived=waived) == []
    assert len(scanners.unhomed_evals(src, "harness/x.py", homed=homed, waived={})) == 1


def _calls_eval_home(rel):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    return any(isinstance(n, ast.Call) and scanners._call_name(n) == "eval_home" for n in ast.walk(tree))


def test_every_eval_or_probe_entry_runs_from_a_scratch_home_or_says_why_not():
    unhomed = scanners.scan_tree(REPO, scanners.unhomed_evals, scanners.is_python)
    assert not unhomed, "an eval or probe on the default home writes rows that pass for real work:\n" + "\n".join(unhomed)
    found = set(scanners.scan_tree(REPO, lambda t, r: [k for _, k in scanners.eval_entry_points(t, r)],
                                   scanners.is_python))
    registered = set(scanners.EVAL_HOMED) | set(scanners.EVAL_WAIVED)
    assert registered <= found, f"registered eval entries no longer in the tree: {sorted(registered - found)}"
    assert not set(scanners.EVAL_HOMED) & set(scanners.EVAL_WAIVED)
    bad = [f"{k} -> {h}" for k, h in scanners.EVAL_HOMED.items() if not _calls_eval_home(h)]
    assert not bad, f"a homed eval's handler must call paths.eval_home: {bad}"
