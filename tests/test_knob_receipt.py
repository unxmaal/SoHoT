"""A registered knob that changes the exam is on the receipt and checked by comparable() (#636)."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import environment
from evals import run as R
from evals.core import Receipt, comparable
from evals.runners.base import BaseRunner
from harness import knobs, paired, publish
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parents[1]


def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway="http://gw.test")
    return Receipt(**{**base, **kw})


def _exam_knobs():
    return [k for k in knobs.KNOBS.values() if k.receipt]


def test_a_knob_an_eval_can_hit_is_recorded_on_the_receipt():
    for k in knobs.KNOBS.values():
        if k.lanes and k.limit and k.predicate == knobs.LIMIT:
            assert k.receipt in ("max_tokens", "knobs"), f"{k.name} changes the exam and is not recorded"


def test_the_settings_a_lane_records_are_its_knobs_defaults():
    got = knobs.settings("code")
    assert got["request_timeout"] == knobs.KNOBS["request_timeout"].default("code")
    assert "runaway_rate" not in got
    assert knobs.settings("tts") == {"runaway_rate": knobs.KNOBS["runaway_rate"].default("tts")}
    assert knobs.settings("image") == {}


def test_an_override_replaces_only_the_knob_it_names():
    got = knobs.settings("code", {"request_timeout": 600.0})
    assert got["request_timeout"] == 600.0
    assert got["load_timeout"] == knobs.KNOBS["load_timeout"].default("code")


def test_the_knob_settings_round_trip_through_the_receipt():
    r = _receipt(knobs={"request_timeout": 600.0})
    assert Receipt.from_dict(r.as_dict()).knobs == {"request_timeout": 600.0}


def test_a_receipt_from_before_knobs_were_recorded_ran_at_the_constants_of_the_time():
    raw = _receipt().as_dict()
    raw.pop("knobs")
    assert Receipt.from_dict(raw).knobs == knobs.settings("code")
    assert Receipt.from_dict({**raw, "modality": "image"}).knobs == {}


@pytest.mark.parametrize("name", [k.name for k in knobs.KNOBS.values() if k.receipt == "knobs"])
def test_runs_at_different_settings_of_an_exam_knob_are_not_ranked_together(name):
    lane = knobs.KNOBS[name].lanes[0]
    a = _receipt(modality=lane, knobs=knobs.settings(lane))
    b = _receipt(modality=lane, knobs=knobs.settings(lane, {name: -1}))
    ok, why = comparable(a, b)
    assert not ok and name in why
    assert comparable(a, _receipt(modality=lane, knobs=knobs.settings(lane)))[0]


def test_a_knob_sweep_names_the_one_knob_that_moved():
    a = _receipt(knobs=knobs.settings("code"))
    b = _receipt(knobs=knobs.settings("code", {"request_timeout": 600.0}))
    assert paired.differences(a, b) == ["knobs.request_timeout"]
    two = _receipt(knobs=knobs.settings("code", {"request_timeout": 600.0, "load_timeout": 60.0}))
    assert paired.differences(a, two) == ["knobs.load_timeout", "knobs.request_timeout"]
    assert paired.is_axis("knobs.request_timeout") and not paired.is_axis("knobs.no_such")


def test_compare_across_reads_a_knob_sweep(tmp_path, capsys):
    files = []
    for n, value in ((1, 180.0), (2, 600.0)):
        f = tmp_path / f"r{n}" / "results.json"
        f.parent.mkdir()
        rec = _receipt(knobs=knobs.settings("code", {"request_timeout": value}))
        f.write_text(json.dumps({"receipt": rec.as_dict(), "summary": {}, "rows": []}),
                     encoding="utf-8")
        files.append(str(f))
    assert R.compare_runs(files) == 1
    assert "request_timeout" in capsys.readouterr().out
    assert R.compare_runs(files, across="knobs.request_timeout") == 0
    assert "180.0 -> 600.0" in capsys.readouterr().out


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {}))


class Answers(BaseRunner):
    def __init__(self):
        self.candidate = self.spec = "org/x"

    def generate(self, case):
        return "", 0


def test_a_run_records_the_knob_settings_it_ran_at(tmp_path, monkeypatch, quiet_receipt):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: Answers())
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="org/x", from_winners=False, gateway="http://gw.test",
        out=str(tmp_path / "out"), split="all", max_tokens=None)
    R._execute(args)
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["knobs"] == knobs.settings("code")


def test_the_published_receipt_keeps_the_knob_settings():
    raw = _receipt(knobs={"request_timeout": 600.0}).as_dict()
    got = publish.exam_receipt(None, {"id": 1, "receipt": json.dumps(raw), "lane": "code"})
    assert got.knobs == {"request_timeout": 600.0}
