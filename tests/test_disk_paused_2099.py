from __future__ import annotations

from harness import disk, paused
from harness.commands import loop as loop_cmd
from tests.test_harness_disk import NOW, inv, make_repo, world  # noqa: F401
from tests.test_harness_fetching_budget import _seed

REAL_SWEEP, REAL_INVENTORY = disk.sweep, disk.inventory


def _paused(w, name):
    make_repo(w.hub, name, size=4096)
    _seed(w.conn, name, 1.0)
    w.conn.commit()
    return paused.save(w.conn, lane="code", inc_spec="org/incumbent", spec=name, proposal=name, out="/runs/x",
                       ident={}, plan={}, done=94, total=304, looks=[])


def _steps(w, monkeypatch):
    monkeypatch.setattr(disk, "sweep", REAL_SWEEP)
    keep = disk.keepers(w.conn, gateway_files=[w.gw], typed={"code": "q3-4b"}, adopted={})
    monkeypatch.setattr(disk, "inventory", lambda conn, *a, **k: REAL_INVENTORY(conn, w.hub, w.gguf, keep))
    loop_cmd._upkeep("disk")
    first = {e.name for e in inv(w).entries}
    loop_cmd._after_verdicts("measure", keep=[])
    return first, {e.name for e in inv(w).entries}


def test_a_paused_measurement_keeps_its_weights_through_the_pre_screen_and_after_measure_disk_steps(world,
                                                                                                    monkeypatch):
    _paused(world, "org/paused")
    assert disk.resumed(world.conn) == {"org/paused"}
    first, after = _steps(world, monkeypatch)
    assert "org/paused" in first and "org/paused" in after


def test_a_settled_measurements_weights_still_go(world, monkeypatch):
    for state in ("done", "stale"):
        name = f"org/{state}"
        paused.settle(world.conn, _paused(world, name), state, "finished")
    assert disk.resumed(world.conn) == set()
    first, _ = _steps(world, monkeypatch)
    assert not first & {"org/done", "org/stale"}
