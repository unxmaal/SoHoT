"""A queued eval or paired adopt runs as items of queue_item seconds, each its own lease, the next taken like any job. #1618."""
import contextlib
import types

import pytest

from evals import run as R
from evals import watch
from harness import exclusive, item_lease, runs
from harness import memory_store as ms
from harness import workqueue as wq
from harness import job_procs
from harness.commands import measure as measure_cmd
from tests.test_repo_looks_1353 import Slices, _measure
from tests.test_resume_813 import _pauses, _rows, world  # noqa: F401

EVAL = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Small-4B"]


@pytest.fixture
def stored(monkeypatch, tmp_path):
    """Every job stored its run at one path, as evals.run links a run to its job."""
    monkeypatch.setattr(runs, "for_job", lambda c, i: {"path": str(tmp_path / "run")})
    return tmp_path / "run"


class Items:
    """A worker's child that runs `items` items of an eval: each but the last ends at its item time and says so."""

    def __init__(self, items: int, then=None):
        self.left, self.calls, self.then = items, [], then

    def __call__(self, argv, cwd=None, stdout=None, stderr=None, env=None):
        self.calls.append({"argv": list(argv), "item": env.get(wq.ITEM_ENV),
                           "leases": [h["id"] for h in item_lease.live(ms.connect())]})
        if self.then and len(self.calls) == 1:
            self.then()
        self.left -= 1
        if self.left > 0 and env.get(wq.ITEM_ENV):
            wq.item_ended(env)
            return types.SimpleNamespace(returncode=watch.PAUSED)
        return types.SimpleNamespace(returncode=0)


def test_a_queued_eval_runs_as_items_each_under_its_own_lease_until_it_finishes(stored):
    job = wq.add(EVAL, title="eval")
    child = Items(3)
    wq.run_pending(popen=child)
    assert [c["item"] for c in child.calls] == [f"{wq.ITEM_S:g}"] * 3
    assert child.calls[0]["argv"] == EVAL
    assert child.calls[1]["argv"][-3:] == ["--out", str(stored), "--resume"] == child.calls[2]["argv"][-3:]
    assert len({c["leases"][0] for c in child.calls}) == 3, "each item takes its own lease"
    got = wq.get(job["id"])
    assert got["state"] == wq.DONE and item_lease.live(ms.connect()) == []


def test_an_item_records_what_it_took_against_its_plan(stored):
    job = wq.add(EVAL, title="eval")
    wq.run_one(wq.get(job["id"]), popen=Items(2))
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and f"of a planned {wq.ITEM_S:.0f}s" in got["note"]


def test_a_lease_says_its_item_is_planned(stored):
    wq.add(EVAL, title="eval")
    seen = []

    def popen(argv, env=None, **kw):
        seen.extend(item_lease.live(ms.connect()))
        return types.SimpleNamespace(returncode=0)
    wq.run_pending(popen=popen)
    assert f"an item of up to {wq.ITEM_S:.0f}s" in seen[0]["detail"]


def test_a_higher_priority_job_added_during_an_item_runs_before_the_next_item(stored):
    order = []
    wq.add(EVAL, title="eval")
    child = Items(2, then=lambda: wq.add(["uv", "run", "python", "-c", "pass"], title="urgent", priority=5))
    def popen(argv, **kw):
        order.append(argv[-1])
        return types.SimpleNamespace(returncode=0) if argv[-1] == "pass" else child(argv, **kw)
    wq.run_pending(popen=popen)
    assert order == [EVAL[-1], "pass", "--resume"]


def test_a_job_with_its_own_stop_is_not_itemised(stored):
    job = wq.add([*EVAL, "--stop-at", "1"], title="stops itself")
    child = Items(2)
    wq.run_pending(popen=child)
    assert child.calls[0]["item"] is None and len(child.calls) == 1
    assert wq.get(job["id"])["state"] == wq.DONE


def test_a_pause_that_is_not_an_item_end_is_not_requeued(stored):
    job = wq.add(EVAL, title="eval")
    wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=watch.PAUSED))
    assert wq.get(job["id"])["state"] == wq.PAUSED


def test_only_gpu_evals_and_paired_adopts_are_itemised():
    assert wq.itemized({"argv": EVAL})
    assert wq.itemized({"argv": ["soh", "adopt", "--lane", "code", "--challenger", "x"]})
    assert not wq.itemized({"argv": ["soh", "adopt", "--confirm", "3"]})
    assert not wq.itemized({"argv": ["soh", "discover", "--loop"]})
    assert not wq.itemized({"argv": EVAL, "resource": "network"})


def _main_args(monkeypatch, argv, environ):
    for k, v in environ.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(R.env, "guard", lambda: None)
    monkeypatch.setattr(exclusive, "held", lambda *a, **k: contextlib.nullcontext(True))
    seen = []
    monkeypatch.setattr(R, "_execute", lambda args: seen.append(args) or 0)
    R._main(R.parse_args(argv))
    return seen[0]


def test_an_eval_under_the_queue_stops_at_its_item_end(monkeypatch):
    args = _main_args(monkeypatch, EVAL[EVAL.index("evals.run") + 1:], {wq.ITEM_ENV: "600"})
    assert args.stop_at is not None and getattr(args, "queue_item", False)


def test_an_eval_with_its_own_stop_ignores_the_item(monkeypatch):
    args = _main_args(monkeypatch, [*EVAL[EVAL.index("evals.run") + 1:], "--stop-after", "30"], {wq.ITEM_ENV: "600"})
    assert not getattr(args, "queue_item", False)


def test_a_queued_adopt_ends_its_item_at_a_look_and_its_next_item_resumes_the_held_run(monkeypatch, world):
    job = wq.add(["soh", "adopt", "--lane", "code", "--challenger", "x"], title="adopt")
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    monkeypatch.setenv(wq.ITEM_ENV, "600")
    fake = Slices([_rows(6, gained=1, lost=1), _rows(12, gained=2, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure() == watch.PAUSED and len(fake.argvs) == 1
    assert job_procs._item_flag(job["id"]).exists()
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["state"] == "paused"
    _measure()
    assert "--resume" in fake.argvs[1]
