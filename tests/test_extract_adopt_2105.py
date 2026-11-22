"""The 2026-11-22 extract adopt: a deploy made a pause stale, one proposal ran twice, dev went first, weights went. #2105."""
import time
from importlib import metadata
from types import SimpleNamespace

from evals import run as R
from evals import watch
from harness import identity, paused
from harness.commands import measure as measure_cmd
from tests.test_interleave_816 import CH as PCH
from tests.test_interleave_816 import INC as PINC
from tests.test_interleave_816 import _pair
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401
from tests.test_resume_813 import CH, INC, Eval, _measure, _pauses, _rows, world  # noqa: F401

OLD = "llamacpp:Old-Q4_K_M"


def _dist(monkeypatch, files):
    def make(path, value):
        p = metadata.PackagePath(path)
        p.hash = metadata.FileHash(f"sha256={value}")
        return p
    monkeypatch.setattr(metadata, "distribution", lambda name: SimpleNamespace(files=[make(*f) for f in files]))
    return identity.dist_digest("mlx-lm")


def test_a_console_script_rewritten_for_another_release_dir_is_the_same_runtime(monkeypatch):
    lib = ("mlx_lm/server.py", "aaa")
    one = _dist(monkeypatch, [lib, ("../../../bin/mlx_lm.server", "shebang-release-132")])
    two = _dist(monkeypatch, [lib, ("../../../bin/mlx_lm.server", "shebang-release-133")])
    assert one == two != ""


def test_a_changed_module_is_another_runtime(monkeypatch):
    one = _dist(monkeypatch, [("mlx_lm/server.py", "aaa")])
    two = _dist(monkeypatch, [("mlx_lm/server.py", "bbb")])
    assert one != two


def _save(conn, spec, proposal, lane="code"):
    return paused.save(conn, lane=lane, inc_spec=INC, spec=spec, proposal=proposal, out=f"/runs/{spec}-{lane}",
                       ident={}, plan={}, done=1, total=2, looks=[])


def test_two_live_pauses_of_one_proposal_in_a_lane_are_one_measurement(world):
    conn = world()
    try:
        _save(conn, OLD, CH)
        _save(conn, CH, CH)
        _save(conn, CH, CH, lane="extract")
        got = measure_cmd.resume_first(conn, [{"name": CH, "lane": "code"}])
    finally:
        conn.close()
    assert sorted((r["name"], r["lane"]) for r in got) == [(CH, "code"), (CH, "extract")]


def test_a_pause_left_under_the_proposals_old_spec_is_settled_stale_and_a_decline_leaves_nothing_to_resume(
        monkeypatch, world):
    conn = world()
    try:
        _save(conn, OLD, CH)
        _save(conn, "llamacpp:Other", "org/other")
    finally:
        conn.close()
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    conn = world()
    try:
        states = {(p["challenger"], p["proposal"]): p["state"] for p in _pauses(conn)}
    finally:
        conn.close()
    assert states[(OLD, CH)] == "stale"
    assert states[("llamacpp:Other", "org/other")] == "paused"
    assert states[(CH, CH)] == "paused"
    rows = _rows(len(fake.rows) + 200, lost=150)
    fake.rows, fake.rc = rows, 0
    data = {"run_id": None, "specs": {INC: INC, CH: CH}, "rows": rows,
            "summary": {INC: {"passed": 10, "total": 10}, CH: {"passed": 1, "total": 10}}}
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: data)
    time.sleep(1.1)
    _measure()
    conn = world()
    try:
        left = [(p["proposal"], p["lane"]) for p in paused.waiting(conn)]
    finally:
        conn.close()
    assert left == [("org/other", "code")]


def test_a_reused_incumbent_cell_keeps_its_place_in_the_challengers_order(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, _ = _pair(monkeypatch, clock)
    first = []

    def taken(path, idents, cases):
        first[:] = [c.id for c in cases[:3]]
        return {"spec": PINC, "digest": "d", "cells": list(first), "runs": {}}
    monkeypatch.setattr(R, "reused_cells", taken)
    rc = R._execute(_args(out, candidates=f"{PINC},{PCH}", stop_at=clock.now + 10.0 * 5 - 1))
    assert rc == watch.PAUSED
    assert runners[PCH].ran[:3] == first
    assert not set(first) & set(runners[PINC].ran)


def test_with_nothing_reused_the_pair_still_alternates_case_by_case(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, log = _pair(monkeypatch, clock)
    R._execute(_args(out, candidates=f"{PINC},{PCH}", stop_at=clock.now + 10.0 * 4 - 1))
    assert log == [PINC, PCH] * 2
    assert runners[PINC].ran == runners[PCH].ran
