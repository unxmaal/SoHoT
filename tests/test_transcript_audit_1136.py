"""Transcript cases after the #1136 audit: retired ones never return, repaired ones show their interface and stated
change after the quote, and a new case enters only when its gold patch passes as the grader runs it."""
import dataclasses
from pathlib import Path

import pytest

from evals import interface, repo
from evals.core import load_cases
from evals.importers import history
from evals.importers import transcripts as tr
from evals.session_cut import HEAD
from tests.test_transcripts_importer import _survey, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = {c.id: c for c in load_cases(ROOT / "evals" / "cases" / "repo" / "transcripts")}
PROBED = {"fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1}


def _case(**params):
    base = next(iter(COMMITTED.values()))
    return dataclasses.replace(base, prompt=HEAD + "## user\nfix add", params={**base.params, **params})


def test_a_session_case_shows_its_interface_then_its_stated_change_after_the_quote():
    lines = ["pkg.mod.f(x: int) -> int"]
    asked = repo.as_asked(_case(interface=lines, stated="`f` doubles `x`.")).prompt
    quote, rest = asked.split(repo.QUOTE_END, 1)
    assert quote.startswith(repo.QUOTE_HEAD) and "> fix add" in quote
    assert rest == f"\n\n{interface.block(lines)}\n\n{repo.STATED_HEAD}\n`f` doubles `x`."
    bare = repo.as_asked(_case(interface=[], stated="")).prompt
    assert bare.endswith(repo.QUOTE_END)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/importers/transcripts.py:CONTEXT")
def test_no_retired_case_is_committed_and_every_repair_names_a_committed_case():
    assert len(COMMITTED) == 11 and not set(tr.RETIRED) & set(COMMITTED)
    assert set(tr.STATED) <= set(COMMITTED) and set(tr.CONTEXT) <= set(COMMITTED)
    for cid, text in tr.STATED.items():
        assert COMMITTED[cid].params["stated"] == text
    for cid, files in tr.CONTEXT.items():
        assert set(files) <= set(COMMITTED[cid].params["context_files"])


def test_every_committed_case_carries_the_interface_its_manifest_row_holds():
    rows = {t["id"]: t for t in tr.fetch()}
    assert set(rows) == set(COMMITTED)
    for cid, case in COMMITTED.items():
        assert "interface" in rows[cid]
        assert case.params.get("interface", []) == rows[cid]["interface"]
        assert tr.convert(rows[cid], tr.redact.Known()).case["params"] == case.params


def test_a_retired_case_is_dropped_by_the_survey_and_never_kept_from_the_manifest(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tr, "RETIRED", {"widget-pr7-request": "mismatch"})
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"retired": 1} and not got["pending"]
    monkeypatch.setattr(tr, "RETIRED", {"widget-pr99-request": "mismatch"})
    gone = {"id": "widget-pr99-request", "fix": "e" * 40}
    world["main"].unlink()
    assert _survey(world, keep={"tasks": [gone]})["tasks"] == []


def test_a_new_task_enters_only_when_its_gold_patch_passes_and_carries_its_interface(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(history, "probe", lambda *a, **k: dict(PROBED))
    asked = []
    monkeypatch.setattr(tr, "admit", lambda case, env=None: asked.append(case["id"]) or "gold_patch_invalid")
    got = _survey(world)
    assert asked == ["widget-pr7-request"] and got["tasks"] == []
    assert got["projects"]["widget"]["dropped"] == {"gold_patch_invalid": 1}
    monkeypatch.setattr(tr, "admit", lambda case, env=None: None)
    monkeypatch.setattr(history, "tests_call", lambda mirror, base, fix: ["pkg.mod.f()"])
    (task,) = _survey(world)["tasks"]
    assert task["interface"] == ["pkg.mod.f()"]
    assert tr.convert(task).case["params"]["interface"] == ["pkg.mod.f()"]


def test_a_kept_task_is_not_admitted_again(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(history, "probe", lambda *a, **k: dict(PROBED))
    first = _survey(world)
    monkeypatch.setattr(tr, "admit", lambda case, env=None: "gold_patch_invalid")
    assert _survey(world, keep=first)["tasks"] == first["tasks"]


def test_admit_takes_the_graders_verdict_on_the_gold_patch(monkeypatch):
    case = {"id": "x-request", "modality": "repo", "prompt": "p", "params": {"variant": "request"}}
    seen = []
    for verdict, want in (("valid", None), ("invalid: reference fails: t (failed)", "gold_patch_invalid"),
                          ("flaky: t", "gold_patch_flaky"), ("error: base: boom", "gold_patch_error")):
        monkeypatch.setattr(repo, "controls", lambda c, env=None, v=verdict: seen.append((c.id, env)) or {"verdict": v})
        assert tr.admit(case, env={"E": "1"}) == want
    assert seen == [("x-request", {"E": "1"})] * 4
