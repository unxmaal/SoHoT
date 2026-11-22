"""A paused run's weights stay whatever group the disk inventory puts them in. #2105."""
import time

from harness import disk, paused
from harness.commands import loop as loop_cmd
from tests.test_disk_paused_2099 import REAL_INVENTORY, REAL_SWEEP
from tests.test_harness_disk import inv, make_repo, verdict, world  # noqa: F401


def _disk_steps(w, monkeypatch):
    monkeypatch.setattr(disk, "sweep", REAL_SWEEP)
    keep = disk.keepers(w.conn, gateway_files=[w.gw], typed={"code": "q3-4b"}, adopted={})
    monkeypatch.setattr(disk, "inventory", lambda conn, *a, **k: REAL_INVENTORY(conn, w.hub, w.gguf, keep))
    loop_cmd._after_verdicts("measure", keep=[])
    return {e.name for e in inv(w).entries}


def test_a_declined_candidate_with_a_live_paused_run_keeps_its_weights(world, monkeypatch):
    make_repo(world.hub, "org/paused", size=4096)
    verdict(world.conn, "org/paused", "declined", tier="adopt", at=time.time() - 60)
    paused.save(world.conn, lane="extract", inc_spec="org/incumbent", spec="org/paused", proposal="org/paused",
                out="/runs/x", ident={}, plan={}, done=138, total=748, looks=[])
    assert disk.REJECTED == next(e for e in inv(world).entries if e.name == "org/paused").group
    assert "org/paused" in _disk_steps(world, monkeypatch)


def test_a_declined_candidate_with_no_live_pause_still_goes(world, monkeypatch):
    make_repo(world.hub, "org/bad", size=4096)
    verdict(world.conn, "org/bad", "declined", tier="adopt", at=time.time() - 60)
    pid = paused.save(world.conn, lane="extract", inc_spec="org/incumbent", spec="org/bad", proposal="org/bad",
                      out="/runs/y", ident={}, plan={}, done=1, total=2, looks=[])
    paused.settle(world.conn, pid, "done", "finished")
    assert "org/bad" not in _disk_steps(world, monkeypatch)
