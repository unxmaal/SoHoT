"""A read that cannot answer is not read as "nothing": idle clock, deploy settle, lane probes without a store (#1783)."""
import pytest

from harness import deploy, lane_probe, queue_pause, watchdog as wd, watchdog_observe
from tests.test_idle_unload_1157 import DAY, ORNITH, Served
from tests.test_watchdog import Fake


class NoStore(Served):
    """Ornith loaded and seen a day ago; its requests are read by the real probe, here with no store."""

    def last_use(self, conn, since):
        return watchdog_observe.Probes.last_use(self, conn, since)


def test_without_a_store_a_served_model_is_not_called_idle(tmp_path):
    watchdog_observe.observe(Served(tmp_path), None, DAY - 86400)
    world = watchdog_observe.observe(NoStore(tmp_path), None, DAY)
    found, skipped = wd.judge(world)
    assert [f for f in found if f.criterion == "idle_unload"] == []
    assert "no store" in skipped["idle_unload"]
    assert watchdog_observe.Probes().last_use(None, 0) is None


def test_the_same_model_with_a_store_and_no_request_is_given_back(tmp_path):
    watchdog_observe.observe(Served(tmp_path), None, DAY - 86400)
    found, _ = wd.judge(watchdog_observe.observe(Served(tmp_path, asked=DAY - 86400), None, DAY))
    assert [f.evidence["model"] for f in found if f.criterion == "idle_unload"] == [ORNITH]


def _failing(monkeypatch, why):
    def settle():
        raise RuntimeError(why)
    monkeypatch.setattr(deploy, "settle", settle)


@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/queue_pause.py:settle_deploys:except")
def test_a_settle_that_fails_is_none_and_alerts_once_per_failure(monkeypatch):
    said = []
    _failing(monkeypatch, "Refusing to touch a newer store")
    assert queue_pause.settle_deploys(alert=said.append) is None
    assert queue_pause.settle_deploys(alert=said.append) is None
    assert len(said) == 1 and "newer store" in said[0] and "no deploy moves" in said[0]
    _failing(monkeypatch, "store unreachable")
    queue_pause.settle_deploys(alert=said.append)
    assert len(said) == 2 and "unreachable" in said[1]
    monkeypatch.setattr(deploy, "settle", lambda: [])
    assert queue_pause.settle_deploys(alert=said.append) == []
    _failing(monkeypatch, "store unreachable")
    queue_pause.settle_deploys(alert=said.append)
    assert len(said) == 3


def test_a_lane_probe_without_a_store_cannot_say_whether_an_incident_is_due():
    assert lane_probe.due(None, "code", None, DAY) is None


def test_a_wake_without_a_store_says_no_lane_was_probed(tmp_path):
    world = watchdog_observe.observe(Fake(tmp_path), None, DAY)
    assert world.lanes is None and "no store" in world.gaps["lanes"]
