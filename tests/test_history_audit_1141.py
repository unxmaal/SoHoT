"""The #1141 audit's repairs: a stated paragraph after the tests-call block, retired cases gone, mechanism ids ungraded."""
import pytest

from evals import interface, repo
from evals.importers import history

ROW = {"id": "sohot-1", "issue": 1, "pr": 2, "date": "2026-10-23", "base": "a" * 40, "fix": "b" * 40,
       "prompts": {"spec": "# Fix the thing", "symptom": "# The thing breaks"}, "context_files": ["pkg/m.py"],
       "new_files": [], "interface": ["pkg.m.new_fn(a)"], "unlisted": {},
       "fail_to_pass": ["tests/test_m.py::test_behaviour", "tests/test_m.py::test_layout[m.py-7]"],
       "pass_to_pass": ["tests/test_m.py::test_old"]}


@pytest.fixture
def tables(monkeypatch):
    monkeypatch.setattr(history, "STATED", {"sohot-1-spec": "- `new_fn` lives in `pkg/m.py`."})
    monkeypatch.setattr(history, "RETIRED", {"sohot-1-symptom": "the tests pin a design the symptom hides"})
    monkeypatch.setattr(history, "LOOSENED", {"sohot-1": {"tests/test_m.py::test_layout[": "gold layout"}})


def test_a_stated_paragraph_follows_the_tests_call_block_and_is_kept_in_params(tables):
    case = history.convert({**ROW, "variant": "spec"}).case
    block = interface.block(ROW["interface"])
    assert case["prompt"] == f"# Fix the thing\n\n{block}\n\n{history.STATED_HEAD}\n- `new_fn` lives in `pkg/m.py`."
    assert case["params"]["stated"] == "- `new_fn` lives in `pkg/m.py`."
    assert "#1141" in case["attribution"]["transform"]
    repo.validate(case["id"], case["params"])


def test_a_case_with_nothing_stated_keeps_its_prompt(tables, monkeypatch):
    monkeypatch.setattr(history, "STATED", {})
    case = history.convert({**ROW, "variant": "spec"}).case
    assert history.STATED_HEAD not in case["prompt"] and "stated" not in case["params"]


def test_a_retired_case_leaves_the_manifest_rows_and_its_other_variant_stays(tables):
    got = history.fetch_rows({"tasks": [ROW]}, dropped={})
    assert [r["variant"] for r in got] == ["spec"]


def test_a_mechanism_id_is_left_ungraded_and_the_behaviour_ids_stay(tables):
    params = history.convert({**ROW, "variant": "spec"}).case["params"]
    assert params["fail_to_pass"] == ["tests/test_m.py::test_behaviour"]
    assert params["pass_to_pass"] == ["tests/test_m.py::test_old"]


def test_every_table_entry_names_a_committed_task():
    tasks = {t["id"] for src in history.repos() for t in history.manifest(src.manifest)["tasks"]}
    cases = {f"{t}-{v}" for t in tasks for v in history.VARIANTS}
    assert set(history.STATED) <= cases and set(history.RETIRED) <= cases and set(history.LOOSENED) <= tasks
    assert not set(history.STATED) & set(history.RETIRED)
