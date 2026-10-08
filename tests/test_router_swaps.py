"""An eval records the router evicting its model mid-run, and comparable() refuses that run (#649)."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import environment
from evals import run as R
from evals.core import Receipt, comparable
from evals.runners.base import BaseRunner
from harness import memory_store as ms
from harness import publish, router, runs
from tests.test_publish import _exam, _exams, store  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
OURS = "Ornith-1.5-35B-Q4_K_M"


class FakeRouter:
    """GET /models as llama-server's router answers it; None plays an unreachable router."""

    def __init__(self, **models):
        self.models = dict(models)
        self.down = False

    def get(self, path):
        assert path == "/models"
        if self.down:
            raise OSError("connection refused")
        return {"data": [{"id": k, "status": {"value": v}} for k, v in self.models.items()]}


def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="http://gw.test")
    return Receipt(**{**base, **kw})


def test_an_eviction_between_cases_is_recorded_with_who_took_the_slot():
    fake = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake.get)
    w.look("a", "start")
    w.look("a", "end")
    fake.models = {OURS: "unloaded", "imajev-4b": "loaded"}
    w.look("b", "start")
    assert w.swaps == [{"case": "b", "at": "start", "status": "unloaded",
                        "resident": ["imajev-4b"]}]


def test_a_reload_in_progress_after_the_model_was_held_is_a_swap():
    fake = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake.get)
    w.look("a", "end")
    fake.models = {OURS: "loading", "imajev-4b": "loaded"}
    w.look("b", "start")
    assert [s["status"] for s in w.swaps] == ["loading"]


def test_the_first_cold_load_is_not_a_swap():
    fake = FakeRouter(**{OURS: "unloaded"})
    w = router.Watch(OURS, get=fake.get)
    w.look("a", "start")
    fake.models[OURS] = "loaded"
    w.look("a", "end")
    assert w.swaps == []


def test_a_second_model_joining_a_free_slot_is_not_a_swap():
    fake = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake.get)
    w.look("a", "start")
    fake.models["imajev-4b"] = "loaded"
    w.look("a", "end")
    w.look("b", "start")
    assert w.swaps == []


def test_an_unreachable_router_is_unknown_not_an_eviction():
    fake = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake.get)
    w.look("a", "end")
    fake.down = True
    w.look("b", "start")
    assert w.swaps == []


def test_only_router_candidates_are_watched():
    assert router.model_for("llamacpp:" + OURS, route=lambda s, g: (router.url(), OURS)) == OURS
    assert router.model_for("org/x", route=lambda s, g: ("http://127.0.0.1:8080", "org/x")) == ""
    assert router.model_for("org/x", route=lambda s, g: ("", "")) == ""

    def unservable(spec, gateway):
        raise ValueError("not a text spec")
    assert router.model_for("image:flux", route=unservable) == ""


def test_the_swaps_round_trip_through_the_receipt_and_an_old_receipt_has_none():
    swaps = {"llamacpp:x": [{"case": "b", "at": "start", "status": "unloaded", "resident": []}]}
    assert Receipt.from_dict(_receipt(router_swaps=swaps).as_dict()).router_swaps == swaps
    raw = _receipt().as_dict()
    raw.pop("router_swaps")
    assert Receipt.from_dict(raw).router_swaps == {}


def test_a_run_with_a_swap_is_not_ranked_with_anything_including_itself():
    dirty = _receipt(router_swaps={"llamacpp:x": [{"case": "b", "at": "start",
                                                   "status": "unloaded", "resident": ["y"]}]})
    clean = _receipt()
    for a, b in ((dirty, clean), (clean, dirty), (dirty, dirty)):
        ok, why = comparable(a, b)
        assert not ok and "llamacpp:x" in why and "swap" in why
    assert comparable(clean, clean)[0]


def _write(tmp_path, name, receipt):
    f = tmp_path / name / "results.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"receipt": receipt.as_dict(), "summary": {}, "rows": []}),
                 encoding="utf-8")
    return str(f)


def test_compare_refuses_a_contaminated_run_even_across_an_axis(tmp_path, capsys):
    swaps = {"llamacpp:x": [{"case": "b", "at": "start", "status": "unloaded", "resident": []}]}
    clean = _write(tmp_path, "clean", _receipt(max_tokens=4000))
    dirty = _write(tmp_path, "dirty", _receipt(max_tokens=8000, router_swaps=swaps))
    assert R.compare_runs([clean, dirty]) == 1
    assert R.compare_runs([clean, dirty], across="max_tokens") == 1
    assert "swap" in capsys.readouterr().out


def test_the_published_page_leaves_out_a_contaminated_run(store):
    clean = _exam("code", {"q3-coder": 2}, "2026-10-06T04:36:01")
    dirty = _exam("code", {"granite-4.1-8b": 3}, "2026-10-07T11:22:01")
    dirty["receipt"]["router_swaps"] = {"granite-4.1-8b": [
        {"case": "c1", "at": "start", "status": "unloaded", "resident": ["imajev-4b"]}]}
    runs.record(store, "runs/clean", clean)
    runs.record(store, "runs/dirty", dirty)
    store.commit()
    _, exams = _exams(store)
    shown = {r["candidate"] for e in exams for r in e["rows"]}
    assert "q3-coder" in shown and "granite-4.1-8b" not in shown


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {}))


class Evicted(BaseRunner):
    """Answers every case; the router evicts its model after the first one."""

    def __init__(self, fake):
        self.candidate = self.spec = "llamacpp:" + OURS
        self.fake = fake
        self.calls = 0

    def generate(self, case):
        self.calls += 1
        self.fake.models[OURS] = "loaded"
        if self.calls == 1:
            self.fake.models = {OURS: "unloaded", "imajev-4b": "loaded"}
        return "", 0


def _run(tmp_path, monkeypatch, runner, model):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    monkeypatch.setattr(router, "model_for", lambda *a, **k: model)
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="decide", candidates="org/x", from_winners=False, gateway="http://gw.test",
        out=str(tmp_path / "out"), split="all", max_tokens=None)
    R._execute(args)
    return json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))


def test_a_run_whose_model_the_router_evicts_records_it_and_cannot_be_ranked(
        tmp_path, monkeypatch, quiet_receipt):
    fake = FakeRouter(**{OURS: "loaded"})
    monkeypatch.setattr(router, "_get", fake.get)
    data = _run(tmp_path, monkeypatch, Evicted(fake), OURS)
    got = data["receipt"]["router_swaps"]["llamacpp:" + OURS]
    assert got and got[0]["at"] == "end" and got[0]["resident"] == ["imajev-4b"]
    rec = Receipt.from_dict(data["receipt"])
    assert not comparable(rec, rec)[0]


def test_a_run_off_the_router_records_no_swaps(tmp_path, monkeypatch, quiet_receipt):
    fake = FakeRouter(**{OURS: "loaded"})
    monkeypatch.setattr(router, "_get", fake.get)
    data = _run(tmp_path, monkeypatch, Evicted(fake), "")
    assert data["receipt"]["router_swaps"] == {}


def test_publish_reads_the_swaps_off_the_stored_receipt():
    raw = _receipt(router_swaps={"k": [{"case": "a"}]}).as_dict()
    got = publish.exam_receipt(None, {"id": 1, "receipt": json.dumps(raw), "lane": "code"})
    assert got.router_swaps == {"k": [{"case": "a"}]}
