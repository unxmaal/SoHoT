"""#1921: `soh quarantine` sizes the quarantine dirs and deletes only exact copies of a file that stays."""
import json
import os

import pytest

from harness import cli, quarantine

OLD, NEW = "quarantine-2026-11-09", "quarantine-2026-11-10"


def put(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def hf(tmp_path, monkeypatch):
    root = tmp_path / "hf"
    (root / "gguf").mkdir(parents=True)
    (root / "hub").mkdir()
    monkeypatch.setenv("HF_HOME", str(root))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(root / "gguf"))
    monkeypatch.delenv("HF_ROOT", raising=False)
    monkeypatch.setattr(cli.env, "guard", lambda *a, **k: None)
    body = bytes(range(256)) * 64
    near = bytearray(body)
    near[len(near) // 2] ^= 1
    put(root / OLD / "mtp.gguf", body)
    put(root / NEW / "mtp.gguf", body)
    put(root / OLD / "drafter.gguf", body + b"d")
    put(root / NEW / "drafter.gguf", bytes(near) + b"d")
    put(root / OLD / "shard.gguf", b"s" * 100)
    put(root / NEW / "shard.gguf", b"s" * 101)
    return root


def run(*argv, capsys=None):
    rc = cli.main(["quarantine", "--json", *argv])
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_the_dirs_are_listed_oldest_first_with_their_bytes(hf, capsys):
    rc, got = run(capsys=capsys)
    assert rc == 0
    assert [(os.path.basename(r["dir"]), r["files"]) for r in got["dirs"]] == [(OLD, 3), (NEW, 3)]
    assert got["dirs"][0]["bytes"] == 2 * 16384 + 1 + 100
    assert got["dirs"][1]["bytes"] == 2 * 16384 + 1 + 101


def test_a_dry_run_names_the_exact_copy_and_deletes_nothing(hf, capsys):
    rc, got = run("--dedupe", capsys=capsys)
    assert rc == 0
    assert [(p["keep"], p["drop"]) for p in got["pairs"]] == [(str(hf / OLD / "mtp.gguf"), str(hf / NEW / "mtp.gguf"))]
    assert got["bytes"] == 16384
    assert all((hf / d / n).exists() for d in (OLD, NEW) for n in ("mtp.gguf", "drafter.gguf", "shard.gguf"))


def test_apply_deletes_only_the_exact_copy_never_a_near_identical_one(hf, capsys):
    rc, got = run("--dedupe", "--apply", capsys=capsys)
    assert rc == 0
    assert not (hf / NEW / "mtp.gguf").exists()
    assert (hf / OLD / "mtp.gguf").read_bytes() == bytes(range(256)) * 64
    assert (hf / NEW / "drafter.gguf").exists() and (hf / OLD / "drafter.gguf").exists()
    assert (hf / NEW / "shard.gguf").exists() and (hf / OLD / "shard.gguf").exists()
    assert got["bytes"] == 16384
    assert sum(r["bytes"] for r in got["before"]) - sum(r["bytes"] for r in got["dirs"]) == 16384


def test_apply_without_dedupe_is_refused(hf, capsys):
    rc, got = run("--apply", capsys=capsys)
    assert rc == 1 and not got["ok"]
    assert (hf / NEW / "mtp.gguf").exists()


def test_a_file_no_other_file_matches_in_size_is_never_read(hf):
    read = []
    quarantine.plan(digest=lambda p: read.append(p.name) or quarantine.sha256(p))
    assert sorted(read) == ["drafter.gguf", "drafter.gguf", "mtp.gguf", "mtp.gguf"]


def test_a_copy_a_hub_snapshot_links_to_is_refused(hf):
    snap = hf / "hub" / "models--o--r" / "snapshots" / "main"
    snap.mkdir(parents=True)
    (snap / "mtp.gguf").symlink_to(hf / NEW / "mtp.gguf")
    pairs, refused = quarantine.plan()
    assert pairs == []
    assert [(p, "points at it" in w) for p, w in refused] == [(hf / NEW / "mtp.gguf", True)]


def test_a_hard_linked_copy_is_refused(hf):
    blob = hf / "hub" / "models--o--r" / "blobs" / "abc"
    blob.parent.mkdir(parents=True)
    os.link(hf / NEW / "mtp.gguf", blob)
    pairs, refused = quarantine.plan()
    assert pairs == []
    assert [p for p, _ in refused] == [hf / NEW / "mtp.gguf"]
    assert quarantine.drop(pairs) == [] and blob.exists()


def test_two_names_for_one_file_are_not_a_duplicate(hf):
    os.link(hf / OLD / "mtp.gguf", hf / OLD / "mtp.1.gguf")
    pairs, refused = quarantine.plan()
    assert {(p.keep.path.name, p.drop.path.parent.name) for p in pairs} == {("mtp.1.gguf", NEW)}
    assert (hf / OLD / "mtp.gguf") in [p for p, _ in refused]
    assert quarantine.sizes()[0] == {"dir": str(hf / OLD), "files": 4, "bytes": 2 * 16384 + 1 + 100}


def test_a_link_inside_the_quarantine_is_never_a_copy(hf):
    (hf / NEW / "mtp.gguf").unlink()
    (hf / NEW / "mtp.gguf").symlink_to(hf / OLD / "mtp.gguf")
    pairs, refused = quarantine.plan()
    assert pairs == []
    assert [p for p, _ in refused] == [hf / NEW / "mtp.gguf"]


def test_a_copy_changed_after_hashing_is_not_deleted(hf):
    pairs, _ = quarantine.plan()
    put(hf / NEW / "mtp.gguf", bytes(16384))
    os.utime(hf / NEW / "mtp.gguf", ns=(pairs[0].drop.mtime_ns + 10**9,) * 2)
    got = quarantine.drop(pairs)
    assert [r.get("error") for r in got] == ["changed since it was hashed"]
    assert (hf / NEW / "mtp.gguf").read_bytes() == bytes(16384)


def test_a_file_outside_the_quarantine_is_never_deleted(hf):
    outside = put(hf / "gguf" / "mtp.gguf", bytes(range(256)) * 64)
    pairs, _ = quarantine.plan()
    assert [p.drop.path for p in pairs] == [hf / NEW / "mtp.gguf"]
    moved = [quarantine.Pair(pairs[0].keep, quarantine.File(outside, *_stat(outside)), pairs[0].sha256)]
    assert [r["error"] for r in quarantine.drop(moved)] == ["outside every quarantine dir"]
    assert outside.exists()


def _stat(p):
    st = os.lstat(p)
    return st.st_size, (st.st_dev, st.st_ino), st.st_nlink, st.st_mtime_ns


def test_soh_disk_reports_the_quarantine_size(hf, capsys):
    assert cli.main(["disk", "--json"]) == 0
    out = capsys.readouterr()
    got = json.loads(out.out.strip().splitlines()[-1])
    assert [r["files"] for r in got["quarantine"]] == [3, 3]
    assert "quarantine: 2 dir(s), 6 file(s)" in out.err
