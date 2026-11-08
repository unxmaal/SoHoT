"""Model-affine queue: a job whose model is resident starts first at its priority, and no release unloads a model a ready job names. #1617."""
import types

import pytest

from harness import admission, item_lease, router
from harness import memory_store as ms
from harness import workqueue as wq


def _eval(stem: str) -> list[str]:
    return ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates",
            f"llamacpp:{stem},enable_thinking=true"]


@pytest.fixture
def held(monkeypatch):
    """The router's resident stems, as the test sets them."""
    state = {"resident": []}
    monkeypatch.setattr(admission, "_resident", lambda: state["resident"])
    monkeypatch.setattr(admission, "spec_gb", lambda spec: 8.0)
    return state


def _ran(seen: list):
    def popen(argv, **kw):
        seen.append((argv[-1], item_lease.live(ms.connect())))
        return types.SimpleNamespace(returncode=0)
    return wq.run_pending(popen=popen)


def test_a_job_whose_model_is_resident_starts_before_an_older_one_at_its_priority(held):
    held["resident"] = ["Small-4B"]
    wq.add(_eval("Big-30B"), title="cold")
    wq.add(_eval("Small-4B"), title="warm")
    seen = []
    assert [j["title"] for j in _ran(seen)] == ["warm", "cold"]
    assert seen[0][1][0]["detail"].startswith("resident llamacpp:Small-4B,enable_thinking=true")
    assert "loads llamacpp:Big-30B" in seen[1][1][0]["detail"]


def test_a_higher_priority_job_starts_first_whatever_is_resident(held):
    held["resident"] = ["Small-4B"]
    wq.add(_eval("Big-30B"), title="urgent", priority=5)
    wq.add(_eval("Small-4B"), title="warm")
    assert [j["title"] for j in _ran([])] == ["urgent", "warm"]


def test_run_order_holds_when_nothing_is_resident(held):
    wq.add(_eval("Big-30B"), title="first")
    wq.add(_eval("Small-4B"), title="second")
    assert [j["title"] for j in _ran([])] == ["first", "second"]


class FakeRouter:
    def __init__(self, **models):
        self.models, self.unloads = dict(models), []

    def get(self, path):
        return {"data": [{"id": k, "status": {"value": v}} for k, v in self.models.items()]}

    def post(self, path, body):
        self.unloads.append(body["model"])
        self.models[body["model"]] = "unloaded"
        return {}


@pytest.fixture
def fake(monkeypatch):
    r = FakeRouter(**{"Small-4B": "loaded"})
    monkeypatch.setattr(router, "_get", r.get)
    monkeypatch.setattr(router, "_post", r.post)
    monkeypatch.setattr(router, "protected", lambda *a, **k: set())
    return r


def test_no_release_unloads_a_model_a_ready_job_names_until_that_job_is_gone(fake):
    job = wq.add(_eval("Small-4B"), title="next")
    assert router.release(["Small-4B"], "screened", say=lambda m: None) == []
    assert fake.unloads == []
    wq.cancel(job["id"])
    assert router.release(["Small-4B"], "screened", say=lambda m: None) == ["Small-4B"]


def test_a_memory_unload_still_takes_a_model_a_ready_job_names(fake):
    wq.add(_eval("Small-4B"), title="next")
    assert router.release(["Small-4B"], "memory", keep=set(), proven_idle=True, say=lambda m: None) == ["Small-4B"]


def test_a_job_the_benchmark_hold_keeps_back_keeps_nothing_loaded(fake):
    from harness import hold
    wq.add(_eval("Small-4B"), title="held back")
    assert admission.waiting() == {"Small-4B"}
    hold.hold(ms.connect(), "test: owner hold", scope=hold.BENCHMARKS)
    assert admission.waiting() == set()


def test_model_id_drops_options_and_methods():
    assert admission.model_id("llamacpp:Ornith-1.5-35B-Q4_K_M,enable_thinking=true") == "Ornith-1.5-35B-Q4_K_M"
    assert admission.model_id("best-of:3:llamacpp:Ornith-1.5-35B-Q4_K_M") == "Ornith-1.5-35B-Q4_K_M"
    assert admission.model_id("mlx-community/Qwen2.5-7B-Instruct-4bit") == "mlx-community/Qwen2.5-7B-Instruct-4bit"
