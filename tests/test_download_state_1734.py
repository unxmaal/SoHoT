"""#1734: downloads.state is one declared field, moved only by download_state's compare-and-swap."""
import subprocess
import sys
import time
from pathlib import Path

import pytest
from gauntlet import detectors

from harness import download_state as ds
from harness import downloads, fetching, migration_check
from harness import memory_store as ms
from harness.memory_store.migrations import columns as cols
from tests.gauntlet.registry import REGISTRY

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def w(tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    (hf / "hub").mkdir(parents=True)
    (hf / "gguf").mkdir()
    monkeypatch.setenv("HF_HOME", str(hf))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(hf / "gguf"))
    conn = ms.connect()
    yield conn
    conn.close()
    for rid in list(downloads._HELD):
        downloads.release(rid)


def _gguf(name="m.gguf", whole=True):
    p = downloads.gguf_root() / name
    if whole:
        p.write_bytes(b"GGUF" + bytes(64))
    return p


def _row(conn, rid):
    return dict(conn.execute("SELECT * FROM downloads WHERE id = ?", (rid,)).fetchone())


def _raw(conn, **kw):
    kw = {"repo": "org/raw", "kind": "gguf", "path": "/x/raw.gguf", "reason": "", **kw}
    names = ", ".join(kw)
    rid = conn.execute(f"INSERT INTO downloads ({names}) VALUES ({', '.join('?' * len(kw))})",
                       tuple(kw.values())).lastrowid
    conn.commit()
    return rid


# ---- the table ----------------------------------------------------------------------------------

def test_nothing_leaves_removed_and_every_move_names_its_reasons():
    assert not [m for m in ds.MOVES if m[0] == ds.REMOVED]
    assert all(m[1] in ds.STATES and (m[0] in ds.STATES or m[0] == ds.NONE) for m in ds.MOVES)
    assert all(reasons for reasons in ds.MOVES.values())


def test_a_row_is_born_only_fetching_or_removed(w):
    for state in (ds.COMPLETE, ds.INCOMPLETE, ds.STOOD_DOWN):
        with pytest.raises(ds.IllegalMove):
            ds.born(w, state, ds.STARTED, repo="org/x", kind="gguf", path="/x/a.gguf")
    with pytest.raises(ds.IllegalMove, match="does not set"):
        ds.born(w, ds.FETCHING, ds.STARTED, repo="org/x", kind="gguf", path="/x/a.gguf", complete=1)


# ---- each combination the issue names ---------------------------------------------------------------

def test_a_row_with_no_start_and_no_finish_backfills_to_a_named_state_and_is_never_in_flight(w):
    rid = _raw(w)
    cols._backfill_download_state(w)
    row = _row(w, rid)
    assert (row["state"], row["reason"]) == (ds.INCOMPLETE, ds.BACKFILL)
    assert not downloads.in_flight(row)


def test_complete_with_no_finish_backfills_to_complete_and_complete_mirrors_state(w):
    rid = _raw(w, complete=1, started_at=1.0)
    cols._backfill_download_state(w)
    assert _row(w, rid)["state"] == ds.COMPLETE
    w.execute("UPDATE downloads SET complete = 0 WHERE id = ?", (rid,))
    assert any("state and complete disagree" in b for b in migration_check._downloads(w))


def test_the_backfill_maps_each_timestamp_shape_once_and_leaves_moved_rows_alone(w):
    ids = {"removed": _raw(w, started_at=1.0, finished_at=2.0, removed_at=3.0, complete=1),
           "fetching": _raw(w, started_at=1.0),
           "incomplete": _raw(w, started_at=1.0, finished_at=2.0),
           "complete": _raw(w, started_at=1.0, finished_at=2.0, complete=1)}
    moved = _raw(w, started_at=1.0, state=ds.STOOD_DOWN, reason=ds.OFFLINE_GAP)
    cols._backfill_download_state(w)
    assert {k: _row(w, rid)["state"] for k, rid in ids.items()} == {k: k for k in ids}
    assert (_row(w, moved)["state"], _row(w, moved)["reason"]) == (ds.STOOD_DOWN, ds.OFFLINE_GAP)


def test_a_removal_of_a_download_a_live_process_holds_is_refused(w):
    p = _gguf(whole=False)
    rid = downloads.start(w, "org/m", downloads.GGUF, p, file=p.name)
    with pytest.raises(downloads.Busy):
        downloads.removed(w, p, by="lh disk")
    row = _row(w, rid)
    assert (row["state"], row["removed_at"]) == (ds.FETCHING, None)
    assert not downloads.drift(w)["gone"], "a GGUF still landing is not gone"


def test_a_stood_down_download_is_not_a_failed_one(w, monkeypatch):
    from tests.test_funnel_925 import _seen
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    for name in ("org/down", "org/broke"):
        _seen(w, name)
        ms.decide(w, name, "queued", tier="inspect", detail=f"fits: {name}")
    good = downloads.start(w, "org/down", downloads.GGUF, _gguf("down.gguf"), proposal="org/down")
    assert downloads.finish(w, good)["state"] == ds.COMPLETE
    bad = downloads.start(w, "org/broke", downloads.GGUF, _gguf("broke.gguf", whole=False), proposal="org/broke")
    assert downloads.finish(w, bad, failed=True)["state"] == ds.INCOMPLETE
    assert downloads.stand_down(w, "org/down", ds.OFFLINE_GAP) == 1
    assert (_row(w, good)["state"], _row(w, good)["complete"]) == (ds.STOOD_DOWN, 0)
    rows = {r["name"]: r for r in fetching.queued(w)}
    assert rows["org/down"]["failed_at"] is None
    assert rows["org/broke"]["failed_at"]


def test_a_stand_down_needs_a_reason(w):
    rid = downloads.start(w, "org/m", downloads.GGUF, _gguf())
    downloads.finish(w, rid)
    with pytest.raises(ds.IllegalMove):
        downloads.stand_down(w, "org/m", "")
    assert _row(w, rid)["state"] == ds.COMPLETE


def test_a_finished_row_is_reopened_only_for_a_named_reason(w):
    p = _gguf()
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    first = downloads.finish(w, rid)
    with pytest.raises(ds.IllegalMove, match="no reason"):
        downloads.start(w, "org/m", downloads.GGUF, p)
    row = _row(w, rid)
    assert (row["state"], row["finished_at"]) == (ds.COMPLETE, first["finished_at"])
    again = downloads.start(w, "org/m", downloads.GGUF, p, reason=ds.REFETCH)
    row = _row(w, again)
    assert (again, row["state"], row["reason"], row["finished_at"]) == (rid, ds.FETCHING, ds.REFETCH, None)


def test_a_fetching_row_nobody_holds_is_abandoned_whatever_its_age_and_a_start_takes_it_over(w):
    p = _gguf(whole=False)
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    downloads.release(rid)
    row = _row(w, rid)
    assert row["started_at"] > time.time() - 60
    assert not downloads.in_flight(row)
    assert downloads.liveness(row) == ds.ABANDONED
    assert downloads.start(w, "org/m", downloads.GGUF, p) == rid
    assert (_row(w, rid)["reason"], downloads.liveness(_row(w, rid))) == (ds.ABANDONED, ds.FETCHING)


def test_a_fetching_row_with_no_lock_file_is_abandoned_not_in_flight(w):
    p = _gguf(whole=False)
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    downloads.release(rid)
    downloads.lock_path(downloads.key(p)).unlink()
    assert downloads.held_elsewhere(downloads.key(p)) is None
    assert not downloads.in_flight(_row(w, rid))


# ---- racing writers ----------------------------------------------------------------------------------

def test_a_second_start_on_a_path_being_downloaded_loses(w):
    p = _gguf(whole=False)
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    with pytest.raises(downloads.Busy):
        downloads.start(w, "org/m", downloads.GGUF, p, reason=ds.REFETCH)
    assert [r["id"] for r in downloads.live(w, path=p)] == [rid]


def test_a_start_in_another_process_loses_to_a_live_one(w, tmp_path):
    p = _gguf(whole=False)
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    child = ("import sys\nfrom harness import downloads, memory_store as ms\n"
             "try:\n    downloads.start(ms.connect(), 'org/m', downloads.GGUF, sys.argv[1])\n"
             "except downloads.Busy:\n    sys.exit(3)\n")
    got = subprocess.run([sys.executable, "-c", child, str(p)], cwd=REPO, timeout=60)
    assert got.returncode == 3
    assert _row(w, rid)["state"] == ds.FETCHING


def test_a_second_writer_of_the_same_move_loses(w):
    rid = downloads.start(w, "org/m", downloads.GGUF, _gguf())
    assert ds.move(w, rid, ds.FETCHING, ds.COMPLETE, ds.FINISHED, finished_at=1.0)
    assert not ds.move(w, rid, ds.FETCHING, ds.INCOMPLETE, ds.FAILED, finished_at=2.0)
    w.commit()
    row = _row(w, rid)
    assert (row["state"], row["finished_at"]) == (ds.COMPLETE, 1.0)
    downloads.release(rid)


def test_a_finish_that_loses_its_move_writes_nothing(w):
    p = _gguf()
    rid = downloads.start(w, "org/m", downloads.GGUF, p)
    assert downloads.finish(w, rid, failed=True)["moved"]
    late = downloads.finish(w, rid)
    assert not late["moved"]
    assert (late["state"], _row(w, rid)["state"]) == (ds.INCOMPLETE, ds.INCOMPLETE)


# ---- one writer ----------------------------------------------------------------------------------------

def test_downloads_state_has_one_guarded_writer():
    trees = detectors.parse(detectors.sources(REPO, production=REGISTRY.production, lister=REGISTRY.files))
    hits = detectors.unguarded_transition(trees, REGISTRY.production)
    assert not [h for h in hits if "downloads" in h.site or "download_" in h.site]
    writers = {rel for rel, tree in trees.items() if "/migrations/" not in rel
               for _n, table, col, _g in detectors._state_writes(tree) if table == "downloads"}
    assert writers == {"harness/download_state.py"}
