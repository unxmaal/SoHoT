"""#1931: the downloads backfill asks only this machine's rows whether a path is recorded and whose it was."""
import json
from pathlib import Path

from harness import download_state as ds, downloads, machine, paths
from harness import memory_store as ms

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}
T = 1791000000.0


def _machines(conn) -> tuple[int, int]:
    """(this machine A, machine B) in one shared store, this process answering as A."""
    me = ms.remember_machine(conn)
    other = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    conn.commit()
    return me, other


def _theirs(conn, other: int, repo: str, kind: str, path) -> int:
    """Machine B's newer row for `path`, written as B would: start() on this machine reopens A's own row instead."""
    rid = downloads.record(conn, repo, kind, Path(path).with_name("b-" + Path(path).name))["id"]
    conn.execute("UPDATE downloads SET machine_id = ?, path = ? WHERE id = ?", (other, downloads.key(path), rid))
    conn.commit()
    return rid


def _rows(conn) -> list[tuple]:
    return [(r["machine_id"], r["path"], r["state"], r["repo"])
            for r in conn.execute("SELECT machine_id, path, state, repo FROM downloads ORDER BY id")]


def test_another_machines_row_for_a_path_never_stops_this_machine_recording_its_own_copy(tmp_path):
    hub, ggufs = tmp_path / "hub", tmp_path / "gguf"
    ggufs.mkdir()
    (ggufs / "here-Q4_K_M.gguf").write_bytes(b"GGUF" + b"\0" * 12)
    manifest = paths.home() / "gguf-sources.json"
    manifest.write_text(json.dumps({"org/here": "here-Q4_K_M.gguf", "org/gone": "gone-Q4_K_M.gguf"}),
                        encoding="utf-8")
    conn = ms.connect()
    try:
        me, other = _machines(conn)
        _theirs(conn, other, "org/here", downloads.GGUF, ggufs / "here-Q4_K_M.gguf")
        # B's copy of a file A does not have: A's backfill must leave B's row as B left it.
        _theirs(conn, other, "org/gone", downloads.GGUF, ggufs / "gone-Q4_K_M.gguf")
        downloads.backfill(conn, hub, ggufs, manifest)
        here, gone = downloads.key(ggufs / "here-Q4_K_M.gguf"), downloads.key(ggufs / "gone-Q4_K_M.gguf")
        assert (other, here, ds.INCOMPLETE, "org/here") in _rows(conn)
        assert (other, gone, ds.INCOMPLETE, "org/gone") in _rows(conn)
        assert (me, here, ds.COMPLETE, "org/here") in _rows(conn)
        assert [r["path"] for r in downloads.live(conn)] == [here]
    finally:
        conn.close()


def test_a_partial_removal_takes_this_machines_repo_for_its_dir_never_anothers(tmp_path):
    hub, ggufs = tmp_path / "hub", tmp_path / "gguf"
    snap = hub / "models--org--mine" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    (hub / "models--org--mine" / "refs").mkdir()
    (hub / "models--org--mine" / "refs" / "main").write_text("abc", encoding="utf-8")
    dir_ = hub / "models--org--mine"
    conn = ms.connect()
    try:
        me, other = _machines(conn)
        downloads.record(conn, "org/mine", downloads.HUB, dir_)
        _theirs(conn, other, "org/theirs", downloads.HUB, dir_)
        conn.executescript("CREATE TABLE disk_removals (id INTEGER PRIMARY KEY, path TEXT NOT NULL, "
                     "repo TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, "
                     "verdict_id INTEGER, source TEXT NOT NULL DEFAULT '', removed_at REAL NOT NULL)")
        conn.execute("INSERT INTO disk_removals (id, path, repo, grp, bytes, source, removed_at) "
                     "VALUES (1,?,?,?,?,?,?)",
                     (str(dir_ / "blobs" / "x.incomplete"), "", "incomplete", 5, "discover", T))
        conn.commit()
        downloads.backfill(conn, hub, ggufs, paths.home() / "gguf-sources.json")
        partial = downloads.key(dir_ / "blobs" / "x.incomplete")
        assert (me, partial, ds.REMOVED, "org/mine") in _rows(conn)
    finally:
        conn.close()
