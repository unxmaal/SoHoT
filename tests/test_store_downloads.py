"""#411: weights on disk are rows, written by the fetch tier and lh disk."""
import argparse
import json
import os
import time

import pytest

from harness import cli, disk, downloads, fetching, gguf
from harness import memory_store as ms

NOW = 2_000_000_000.0
DAY = 24 * 3600
GATEWAY = """model_list:
  - model_name: q3-4b
    litellm_params:
      model: openai/mlx-community/Qwen3-4B-Instruct-2507-4bit
"""


@pytest.fixture
def w(tmp_path, monkeypatch):
    hf = tmp_path / "hf"
    (hf / "hub").mkdir(parents=True)
    (hf / "gguf").mkdir()
    monkeypatch.setenv("HF_HOME", str(hf))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(hf / "gguf"))
    monkeypatch.setattr(cli.env, "guard", lambda *a, **k: None)
    gw = tmp_path / "gateway.yaml"
    gw.write_text(GATEWAY, encoding="utf-8")
    conn = ms.connect()
    yield argparse.Namespace(hub=hf / "hub", gguf=hf / "gguf", conn=conn,
                             gw=gw, tmp=tmp_path)
    conn.close()


def snapshot(repo, files=("config.json", "model.safetensors")):
    d = downloads.hub_dir(repo)
    snap = d / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (d / "blobs").mkdir()
    for f in files:
        blob = d / "blobs" / f"b-{f}"
        blob.write_bytes(b"x" * 100)
        (snap / f).symlink_to(blob)
    return d


def inv(w):
    keep = disk.keepers(w.conn, gateway_files=[w.gw], typed={"code": "q3-4b"},
                        adopted={})
    return disk.inventory(w.conn, w.hub, w.gguf, keep)


# ---- have() is a query --------------------------------------------------------

def test_a_complete_download_on_disk_with_no_row_is_not_had(w):
    """The negative control: the hub tree is not the record of a fetch."""
    snapshot("org/m")
    assert not fetching.have("org/m", w.conn)
    downloads.record(w.conn, "org/m", downloads.HUB, downloads.hub_dir("org/m"))
    assert fetching.have("org/m", w.conn)


def test_a_card_only_snapshot_is_recorded_incomplete_and_not_had(w):
    d = snapshot("org/card", ("README.md", "LICENSE"))
    row = downloads.record(w.conn, "org/card", downloads.HUB, d)
    assert row["complete"] == 0 and row["files"] == 2
    assert not fetching.have("org/card", w.conn)
    assert fetching.missing("org/card", w.conn) == ["org/card"]


def test_a_recorded_download_whose_dir_is_gone_is_not_had(w):
    d = snapshot("org/m")
    downloads.record(w.conn, "org/m", downloads.HUB, d)
    import shutil
    shutil.rmtree(d)
    assert not fetching.have("org/m", w.conn)


def test_another_machines_row_is_not_had_here(w):
    d = snapshot("org/m")
    downloads.record(w.conn, "org/m", downloads.HUB, d)
    other = ms.remember_machine(w.conn, {
        "fingerprint": "Other/os/arch", "hw_model": "Other", "os": "os",
        "arch": "arch", "memory_gb": 1, "accelerator": "", "runtimes": "",
        "ceiling_gb": 1})
    w.conn.execute("UPDATE downloads SET machine_id = ?", (other,))
    assert not fetching.have("org/m", w.conn)


def test_requires_is_what_the_config_said_when_it_landed(w):
    d = downloads.hub_dir("org/8bit") / "snapshots" / "abc"
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps(
        {"text_tokenizer": "org/base", "_name_or_path": "org/parent"}),
        encoding="utf-8")
    downloads.record(w.conn, "org/8bit", downloads.HUB, d.parent.parent)
    assert fetching.requires("org/8bit", w.conn) == ["org/base"]
    assert fetching.missing("org/8bit", w.conn) == ["org/base"]


def test_a_failed_download_is_recorded_incomplete(w):
    ms.record(w.conn, ms.Seen(name="org/a", source="t", lane="stt",
                              kind="weights", resolved="org/a"))
    ms.decide(w.conn, "org/a", "queued", tier="inspect")

    def boom(repo_id):
        downloads.hub_dir(repo_id).mkdir(parents=True)
        raise RuntimeError("connection reset")
    fetching.run(w.conn, {"org/a": 2 * fetching.GIB}, snapshot=boom,
                 free=900 * fetching.GIB)
    row = w.conn.execute("SELECT * FROM downloads").fetchone()
    assert row["complete"] == 0 and row["finished_at"] is not None
    assert not fetching.have("org/a", w.conn)


# ---- lh disk: removal stamps the row, drift is reported -------------------------

def test_a_dir_no_row_explains_is_drift_and_never_deleted(w):
    d = snapshot("org/stray")
    i = inv(w)
    e = next(e for e in i.entries if e.path == str(d))
    assert e.unrecorded and e.group == disk.UNKNOWN
    assert disk.drift(i)["unrecorded"] == [str(d)]
    assert disk.delete(i, NOW, disk.UNKNOWN, w.conn) == []
    assert d.exists()


def test_recording_drift_makes_an_unknown_deletable_and_stamps_it(w):
    d = snapshot("org/stray")
    assert downloads.record_unrecorded(w.conn, w.hub, w.gguf, {}) == {
        "recorded": 1, "gone": 0}
    i = inv(w)
    assert disk.drift(i) == {"gone": [], "unrecorded": []}
    got = disk.delete(i, NOW, disk.UNKNOWN, w.conn)
    assert [r["path"] for r in got] == [str(d)] and not d.exists()
    row = w.conn.execute("SELECT * FROM downloads").fetchone()
    assert row["removed_by"] == "lh disk" and row["removed_at"] is not None
    assert row["origin"] == downloads.SCAN


def test_a_recorded_keeper_is_never_deleted(w):
    d = snapshot("mlx-community/Qwen3-4B-Instruct-2507-4bit")
    downloads.record(w.conn, "mlx-community/Qwen3-4B-Instruct-2507-4bit",
                     downloads.HUB, d)
    ms.record(w.conn, ms.Seen(name="mlx-community/Qwen3-4B-Instruct-2507-4bit",
                              source="t"))
    ms.decide(w.conn, "mlx-community/Qwen3-4B-Instruct-2507-4bit", "broken",
              tier="screen", at=NOW - 30 * DAY)
    for wanted in (disk.REJECTED, disk.UNKNOWN):
        disk.delete(inv(w), NOW, wanted, w.conn)
    assert d.exists()


def test_a_row_whose_path_is_gone_is_reported_not_guessed(w):
    d = snapshot("org/gone")
    downloads.record(w.conn, "org/gone", downloads.HUB, d)
    import shutil
    shutil.rmtree(d)
    i = inv(w)
    assert [r["repo"] for r in disk.drift(i)["gone"]] == ["org/gone"]
    assert disk.summary(i, NOW)["drift"] == {"gone": 1, "unrecorded": 0}
    assert "1 recorded path(s) gone" in disk.table(i, NOW)
    downloads.record_unrecorded(w.conn, w.hub, w.gguf, {})
    row = w.conn.execute("SELECT removed_by FROM downloads").fetchone()
    assert row["removed_by"] == "absent at scan"


def test_cli_disk_json_reports_drift(w, capsys):
    snapshot("org/stray")
    assert cli.main(["disk", "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["drift"] == {"gone": 0, "unrecorded": 1}
    assert cli.main(["disk", "--record", "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["drift"] == {"gone": 0, "unrecorded": 0}


def test_removing_a_hub_dir_stamps_its_gguf_link_row_too(w):
    d = snapshot("org/T-GGUF", ("t-Q4_K_M.gguf",))
    downloads.record(w.conn, "org/T-GGUF", downloads.HUB, d)
    link = w.gguf / "t-Q4_K_M.gguf"
    link.symlink_to((d / "snapshots" / "abc" / "t-Q4_K_M.gguf").resolve())
    downloads.record(w.conn, "org/T-GGUF", downloads.GGUF, link,
                     file=link.name, origin=downloads.LINK)
    ms.record(w.conn, ms.Seen(name="org/T-GGUF", source="t"))
    ms.decide(w.conn, "org/T-GGUF", "broken", tier="screen", at=NOW - 2 * DAY)
    disk.delete(inv(w), NOW, disk.REJECTED, w.conn)
    rows = w.conn.execute("SELECT kind, removed_by FROM downloads "
                          "ORDER BY kind").fetchall()
    assert [tuple(r) for r in rows] == [("gguf", "lh disk"), ("hub", "lh disk")]
    assert not fetching.have("org/T-GGUF", w.conn)


# ---- backfill ----------------------------------------------------------------

def _at_schema_30(conn):
    conn.execute("DROP TABLE downloads")
    conn.executescript("""
        CREATE TABLE disk_removals (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL,
            repo TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL,
            bytes INTEGER NOT NULL DEFAULT 0, verdict_id INTEGER,
            source TEXT NOT NULL DEFAULT '', removed_at REAL NOT NULL);
    """)
    conn.execute("UPDATE meta SET value = '30' WHERE key = 'schema'")
    conn.commit()


def test_the_migration_backfills_every_source_once(w, monkeypatch):
    for name in ("org/fetched", "org/deleted", "org/card", "org/G-GGUF"):
        ms.record(w.conn, ms.Seen(name=name, source="t", lane="code"))
    fetched = snapshot("org/fetched")
    card = snapshot("org/card", ("README.md",))
    gone = downloads.hub_dir("org/deleted")
    stray = snapshot("org/stray")
    (w.gguf / "G-Q4_K_M.gguf").write_bytes(b"GGUF")
    for name, where in (("org/fetched", fetched / "snapshots" / "abc"),
                        ("org/deleted", gone / "snapshots" / "abc"),
                        ("org/card", card / "snapshots" / "abc")):
        ms.decide(w.conn, name, "queued", tier="fetch",
                  detail="downloaded", run_path=str(where), at=NOW)
    _at_schema_30(w.conn)
    w.conn.execute(
        "INSERT INTO disk_removals (path, repo, grp, bytes, verdict_id, source, "
        "removed_at) VALUES (?,?,?,?,?,?,?)",
        (str(gone), "org/deleted", "rejected", 5, None, "discover", NOW + 9))
    # Removed once, fetched again since: history, not a removal of what is here.
    w.conn.execute(
        "INSERT INTO disk_removals (path, repo, grp, bytes, verdict_id, source, "
        "removed_at) VALUES (?,?,?,?,?,?,?)",
        (str(fetched), "org/fetched", "rejected", 7, None, "lh disk", NOW - 9))
    w.conn.commit()
    (ms.paths.home() / "gguf-sources.json").write_text(
        json.dumps({"org/G-GGUF": "G-Q4_K_M.gguf",
                    "org/old-GGUF": "old.gguf"}), encoding="utf-8")
    w.conn.close()

    w.conn = ms.connect()
    c = w.conn
    assert c.execute("SELECT value FROM meta WHERE key='schema'"
                     ).fetchone()[0] == str(ms.SCHEMA_VERSION)
    assert not ms._columns(c, "disk_removals")
    assert c.execute("SELECT COUNT(*) FROM verdicts WHERE tier = 'fetch' "
                     "AND run_path != ''").fetchone()[0] == 0
    rows = {r["repo"]: dict(r) for r in c.execute(
        "SELECT * FROM downloads ORDER BY removed_at IS NULL, id")}
    assert rows["org/fetched"]["complete"] == 1
    assert rows["org/fetched"]["removed_at"] is None
    assert tuple(c.execute("SELECT removed_at, bytes FROM downloads WHERE repo = ? "
                     "AND removed_at IS NOT NULL", ("org/fetched",)
                     ).fetchone()) == (NOW - 9, 7)
    assert rows["org/fetched"]["finished_at"] == NOW
    assert rows["org/card"]["complete"] == 0
    assert (rows["org/deleted"]["removed_at"], rows["org/deleted"]["removed_by"]
            ) == (NOW + 9, "discover")
    assert rows["org/G-GGUF"]["kind"] == "gguf" and rows["org/G-GGUF"]["complete"]
    assert rows["org/old-GGUF"]["removed_by"] == "absent at backfill"
    assert rows["org/stray"]["origin"] == downloads.BACKFILL
    assert fetching.have("org/fetched", c) and not fetching.have("org/card", c)
    assert gguf.fetched("org/G-GGUF", c) == "G-Q4_K_M"
    assert downloads.drift(c, w.hub, w.gguf) == {"gone": [], "unrecorded": []}
    assert stray.exists() and fetched.exists() and card.exists()
    assert ms.dangling_receipts(c) == []


def test_the_backfill_reads_the_weights_dirs_and_never_writes_them(w):
    snapshot("org/a")
    (w.gguf / "x.gguf").write_bytes(b"GGUF")

    def tree():
        return sorted((str(p), os.lstat(p).st_mtime)
                      for p in w.hub.parent.rglob("*"))
    before = tree()
    time.sleep(0.01)
    downloads.backfill(w.conn, w.hub, w.gguf)
    assert tree() == before


def test_a_keeper_spec_is_resolved_through_the_stored_candidate(w):
    """#429: `mflux:z-image-turbo` names no repo by its spelling; the row does."""
    ms.record(w.conn, ms.Seen(name="org/zimg", source="t", lane="image"))
    w.conn.execute(
        "INSERT INTO candidates (proposal_id, spec, receipt_key, lane, "
        "created_at) VALUES ((SELECT id FROM proposals WHERE name = ?), "
        "?, ?, 'image', 0)", ("org/zimg", "mflux:z-image-turbo",
                              "mflux:z-image-turbo"))
    keep = disk.keepers(w.conn, gateway_files=[w.gw],
                        typed={"image": "mflux:z-image-turbo"}, adopted={})
    assert keep.repos["org/zimg"] == "image default"
    assert not any("names no weights" in p for p in keep.problems)
