"""A stale checkpoint keeps the rows whose case and every side's identity are unchanged; an empty identity keeps none. #2107."""
import json

from evals import watch
from evals import run as R
from tests.test_pause_813 import Ticking, _args, _run, clock, quiet  # noqa: F401


def _identity(monkeypatch, digest: str, changed: set):
    def fake(lane, spec, budget, ladder, overrides, cases, harness="patch"):
        return {"digest": digest, "cases": {c.id: ("new" if c.id in changed else "same") for c in cases},
                "parts": {}, "timing": {}, "unresolved": []}
    monkeypatch.setattr(R, "content_identity", fake)


def _paused(monkeypatch, tmp_path, clock, digest="d1"):
    out = tmp_path / "run"
    _identity(monkeypatch, digest, set())
    first = Ticking(clock)
    assert _run(monkeypatch, first, _args(out, stop_at=clock.now + 25.0)) == watch.PAUSED
    assert len(first.ran) >= 2
    return out, first


def test_a_changed_case_reruns_and_an_unchanged_one_keeps_its_row(monkeypatch, tmp_path, quiet, clock):
    out, first = _paused(monkeypatch, tmp_path, clock)
    before = {r["case_id"]: r["wall_s"] for r in watch.read(out)[1]}
    _identity(monkeypatch, "d1", {first.ran[0]})
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) == 0
    assert set(second.ran) & set(first.ran) == {first.ran[0]}
    rows = json.loads((out / "results.json").read_text(encoding="utf-8"))["rows"]
    assert sorted(r["case_id"] for r in rows) == sorted(set(first.ran) | set(second.ran))
    after = {r["case_id"]: r["wall_s"] for r in watch.read(out)[1]}
    assert all(after[c] == before[c] for c in first.ran[1:])


def test_a_changed_run_identity_keeps_no_row(monkeypatch, tmp_path, quiet, clock):
    out, first = _paused(monkeypatch, tmp_path, clock)
    _identity(monkeypatch, "d2", set())
    again = Ticking(clock)
    assert _run(monkeypatch, again, _args(out, resume=True)) == watch.STALE
    assert again.ran == []


def test_an_empty_identity_keeps_nothing(monkeypatch, tmp_path, quiet, clock):
    out, first = _paused(monkeypatch, tmp_path, clock, digest="")
    _identity(monkeypatch, "", {first.ran[0]})
    again = Ticking(clock)
    assert _run(monkeypatch, again, _args(out, resume=True)) == watch.STALE
    assert again.ran == []
    assert len(watch.read(out)[1]) == len(first.ran)


def test_a_checkpoint_from_before_case_identities_keeps_nothing():
    had = {"candidates": ["org/x"], "identities": {"org/x": "a"}}
    now = {"candidates": ["org/x"], "identities": {"org/x": "b"},
           "case_identities": {"org/x": {"digest": "d", "cases": {"c1": "same"}}}}
    assert watch.kept_rows(had, now, [{"case_id": "c1", "candidate": "org/x"}]) == []


def test_another_change_beside_the_identities_keeps_nothing():
    ids = {"org/x": {"digest": "d", "cases": {"c1": "same"}}}
    had = {"candidates": ["org/x"], "identities": {"org/x": "a"}, "case_identities": ids, "max_tokens": 1}
    now = {**had, "identities": {"org/x": "b"}, "max_tokens": 2}
    assert watch.kept_rows(had, now, [{"case_id": "c1"}]) == []
    assert watch.kept_rows(had, {**now, "max_tokens": 1}, [{"case_id": "c1#2"}]) == [{"case_id": "c1#2"}]


def test_a_checkpoint_from_before_case_identities_resumes_when_nothing_else_changed():
    had = {"candidates": ["org/x"], "identities": {"org/x": "a"}}
    assert watch.differs(had, {**had, "case_identities": {"org/x": {"digest": "d", "cases": {}}}}) == []
