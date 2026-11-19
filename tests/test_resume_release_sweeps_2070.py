"""A paused sweep value's continuation is queued on this release; one that cannot be queued is skipped by name. #2070."""
from harness import sweeps, workqueue as wq
from tests.test_knob_sweeps import NOW as SWEEP_NOW, binding_budget, conn, serving  # noqa: F401
from tests.test_resume_release_2070 import _built_by, deployed  # noqa: F401


def test_a_paused_sweep_value_built_by_an_older_release_continues_on_this_one(conn, serving, deployed):
    old, new = deployed
    binding_budget(conn)
    [sw] = sweeps.check(conn, now=SWEEP_NOW)["queued"]
    (_, first), (_, second) = sw["jobs"][:2]
    gone = old / "only-in-108"
    gone.mkdir()
    for j, cwd in ((first, gone), (second, None)):
        conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (wq.PAUSED, j))
        _built_by(conn, j, old, cwd)
    resumed: list = []
    sweeps.settle(conn, now=SWEEP_NOW + 120, resumed=resumed)
    refused, ok = resumed
    assert refused["paused"] == first and refused["job"] is None and "only-in-108" in refused["refused"]
    assert wq.get(ok["job"], conn=conn)["cwd"] == str(new)
    assert "not resumed" in sweeps.render({"settled": [], "resumed": resumed, "planned": []})
