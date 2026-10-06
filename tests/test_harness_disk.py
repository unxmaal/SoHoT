"""#370 / #373: one inventory, one delete decision, shared by `lh disk` and the loop."""
import argparse
import json
import os
import time

import pytest

from harness import cli, disk
from harness import memory_store as ms

NOW = 2_000_000_000.0
DAY = 24 * 3600
GATEWAY = """model_list:
  - model_name: q3-4b
    litellm_params:
      model: openai/mlx-community/Qwen3-4B-Instruct-2507-4bit
  - model_name: eval-4b
    source_repo: unsloth/Qwen3-4B-Instruct-2507-GGUF
    source_file: Qwen3-4B-Instruct-2507-Q4_K_M.gguf
    litellm_params:
      model: openai/Qwen3-4B-Instruct-2507-Q4_K_M
"""


def make_repo(hub, repo, size=1000, mtime=NOW - 10 * DAY):
    d = hub / f"models--{repo.replace('/', '--')}"
    (d / "blobs").mkdir(parents=True)
    (d / "snapshots" / "main").mkdir(parents=True)
    blob = d / "blobs" / "abc"
    blob.write_bytes(b"x" * size)
    (d / "snapshots" / "main" / "model.safetensors").symlink_to(blob)
    os.utime(blob, (mtime, mtime))
    return d


@pytest.fixture
def world(tmp_path, monkeypatch):
    hub, ggufs = tmp_path / "hf" / "hub", tmp_path / "hf" / "gguf"
    hub.mkdir(parents=True)
    ggufs.mkdir()
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(ggufs))
    monkeypatch.delenv("HF_ROOT", raising=False)
    monkeypatch.setattr(cli.env, "guard", lambda *a, **k: None)
    gw = tmp_path / "config.yaml"
    gw.write_text(GATEWAY, encoding="utf-8")
    conn = ms.connect(tmp_path / "d.db")
    yield argparse.Namespace(hub=hub, gguf=ggufs, gw=gw, conn=conn,
                             tmp=tmp_path)
    conn.close()


def verdict(conn, name, outcome, tier="screen", at=NOW - 2 * DAY):
    ms.record(conn, ms.Seen(name=name, source="t"))
    ms.decide(conn, name, outcome, tier=tier, at=at)


def inv(w, typed=None, adopted=None):
    keep = disk.keepers(w.conn, gateway_files=[w.gw],
                        typed=typed or {"code": "q3-4b"},
                        adopted=adopted or {})
    return disk.inventory(w.conn, w.hub, w.gguf, keep, sources={})


def entry(i, name):
    return next(e for e in i.entries if e.name == name)


def test_rejected_past_24_hours_is_deleted_and_recorded(world):
    d = make_repo(world.hub, "org/bad", size=4096)
    verdict(world.conn, "org/bad", "broken", at=NOW - 25 * 3600)
    i = inv(world)
    assert entry(i, "org/bad").group == disk.REJECTED
    got = disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert not d.exists()
    assert got[0]["bytes"] == 4096
    row = world.conn.execute(
        "SELECT repo, bytes, grp FROM disk_removals").fetchone()
    assert (row["repo"], row["bytes"], row["grp"]) == ("org/bad", 4096,
                                                       "rejected")


def test_rejected_inside_24_hours_is_kept(world):
    d = make_repo(world.hub, "org/bad")
    verdict(world.conn, "org/bad", "declined", tier="adopt",
            at=NOW - 23 * 3600)
    i = inv(world)
    assert entry(i, "org/bad").group == disk.REJECTED
    assert disk.delete(i, NOW, disk.REJECTED, world.conn) == []
    assert d.exists()


def test_a_rejected_repo_an_alias_names_is_kept(world):
    d = make_repo(world.hub, "mlx-community/Qwen3-4B-Instruct-2507-4bit")
    verdict(world.conn, "mlx-community/Qwen3-4B-Instruct-2507-4bit", "broken",
            at=NOW - 30 * DAY)
    i = inv(world)
    e = entry(i, "mlx-community/Qwen3-4B-Instruct-2507-4bit")
    assert e.group == disk.KEEP and "alias" in e.why
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert d.exists()


def test_an_adopted_winner_and_an_engine_default_are_kept(world):
    make_repo(world.hub, "ACE-Step/Ace-Step1.5")
    make_repo(world.hub, "org/winner")
    for name in ("ACE-Step/Ace-Step1.5", "org/winner"):
        verdict(world.conn, name, "broken", at=NOW - 30 * DAY)
    i = inv(world, typed={"music": "acestep:acestep-v15-turbo"},
            adopted={"image": "mflux:org/winner"})
    assert entry(i, "ACE-Step/Ace-Step1.5").group == disk.KEEP
    assert entry(i, "org/winner").group == disk.KEEP


def test_tooling_with_no_verdict_is_keep_not_unknown(world):
    make_repo(world.hub, "yuvalkirstain/PickScore_v1")
    make_repo(world.hub, "org/stray")
    i = inv(world)
    assert entry(i, "yuvalkirstain/PickScore_v1").group == disk.KEEP
    assert entry(i, "org/stray").group == disk.UNKNOWN


def test_unknown_is_deleted_only_when_asked_for(world):
    d = make_repo(world.hub, "org/stray")
    i = inv(world)
    assert disk.delete(i, NOW, disk.REJECTED, world.conn) == []
    assert d.exists()
    disk.delete(i, NOW, disk.UNKNOWN, world.conn)
    assert not d.exists()


def test_a_queued_candidate_is_kept(world):
    d = make_repo(world.hub, "org/next")
    verdict(world.conn, "org/next", "broken", at=NOW - 30 * DAY)
    verdict(world.conn, "org/next", "queued", tier="screen",
            at=NOW - 29 * DAY)
    i = inv(world)
    assert entry(i, "org/next").group == disk.QUEUED
    for wanted in (disk.REJECTED, disk.UNKNOWN):
        disk.delete(i, NOW, wanted, world.conn)
    assert d.exists()


def test_retracted_then_rejected_is_rejected(world):
    make_repo(world.hub, "org/again")
    verdict(world.conn, "org/again", "broken", at=NOW - 30 * DAY)
    verdict(world.conn, "org/again", "queued", at=NOW - 20 * DAY)
    verdict(world.conn, "org/again", "broken", at=NOW - 3 * DAY)
    assert entry(inv(world), "org/again").group == disk.REJECTED


def test_an_inspect_refusal_did_not_fetch_so_is_not_rejected(world):
    make_repo(world.hub, "org/manual")
    verdict(world.conn, "org/manual", "declined", tier="inspect",
            at=NOW - 30 * DAY)
    assert entry(inv(world), "org/manual").group == disk.UNKNOWN


def test_deleting_a_gguf_symlink_never_follows_it_into_a_kept_file(world):
    kept = world.gguf / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
    kept.write_bytes(b"k" * 100)
    link = world.gguf / "other.gguf"
    link.symlink_to(kept)
    keep = disk.keepers(world.conn, gateway_files=[world.gw],
                        typed={}, adopted={})
    i = disk.inventory(world.conn, world.hub, world.gguf, keep,
                       sources={"other.gguf": "org/other-GGUF"})
    verdict(world.conn, "org/other-GGUF", "broken", at=NOW - 30 * DAY)
    i = disk.inventory(world.conn, world.hub, world.gguf, keep,
                       sources={"other.gguf": "org/other-GGUF"})
    assert entry(i, "Qwen3-4B-Instruct-2507-Q4_K_M.gguf").group == disk.KEEP
    assert entry(i, "other.gguf").group == disk.REJECTED
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert not link.is_symlink()
    assert kept.read_bytes() == b"k" * 100


def test_deleting_a_hub_repo_removes_its_gguf_symlink(world):
    d = make_repo(world.hub, "org/thing-GGUF")
    link = world.gguf / "thing.gguf"
    link.symlink_to(d / "blobs" / "abc")
    verdict(world.conn, "org/thing-GGUF", "broken", at=NOW - 2 * DAY)
    i = inv(world)
    assert entry(i, "org/thing-GGUF").links == [str(link)]
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert not d.exists() and not link.is_symlink()


def test_a_kept_gguf_link_keeps_the_hub_repo_it_points_into(world):
    d = make_repo(world.hub, "org/rejected-GGUF")
    (world.gguf / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf").symlink_to(
        d / "blobs" / "abc")
    verdict(world.conn, "org/rejected-GGUF", "broken", at=NOW - 30 * DAY)
    i = inv(world)
    assert entry(i, "org/rejected-GGUF").group == disk.KEEP
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert d.exists()


def test_a_hub_repo_holding_a_symlink_to_a_kept_file_leaves_the_file(world):
    kept = world.tmp / "elsewhere.bin"
    kept.write_bytes(b"precious")
    d = make_repo(world.hub, "org/bad")
    (d / "snapshots" / "main" / "evil").symlink_to(kept)
    verdict(world.conn, "org/bad", "broken", at=NOW - 2 * DAY)
    disk.delete(inv(world), NOW, disk.REJECTED, world.conn)
    assert not d.exists()
    assert kept.read_bytes() == b"precious"


def test_a_path_outside_the_roots_is_refused(world):
    outside = world.tmp / "models--org--bad"
    outside.mkdir()
    e = disk.Entry("hub", str(outside), "org/bad", "org/bad", 1, 0,
                   group=disk.REJECTED, decided_at=NOW - 30 * DAY)
    ok, why = disk.safe_to_delete(e, NOW, disk.REJECTED,
                                  (str(world.hub), str(world.gguf)))
    assert not ok and "outside" in why
    i = disk.Inventory(str(world.hub), str(world.gguf), [e], [], [])
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert outside.exists()
    inside = disk.Entry("hub", str(world.hub / "models--org--bad"), "org/bad",
                        "org/bad", 1, 0, group=disk.REJECTED,
                        decided_at=NOW - 30 * DAY)
    (world.hub / "models--org--bad").mkdir()
    assert disk.safe_to_delete(inside, NOW, disk.REJECTED,
                               (str(world.hub), str(world.gguf)))[0]


def test_a_symlinked_repo_dir_is_not_scanned_or_followed(world):
    target = world.tmp / "real"
    target.mkdir()
    (world.hub / "models--org--linked").symlink_to(target)
    assert inv(world).entries == []


def test_unreadable_keepers_refuse_every_deletion(world):
    d = make_repo(world.hub, "org/bad")
    verdict(world.conn, "org/bad", "broken", at=NOW - 30 * DAY)
    empty = world.tmp / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    keep = disk.keepers(world.conn, gateway_files=[empty], typed={},
                        adopted={})
    i = disk.inventory(world.conn, world.hub, world.gguf, keep, sources={})
    with pytest.raises(RuntimeError, match="refusing"):
        disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert d.exists()


def test_a_default_that_names_no_weights_disables_deletion(world):
    keep = disk.keepers(world.conn, gateway_files=[world.gw],
                        typed={"image": "mflux:z-image-turbo"}, adopted={})
    assert any("names no weights" in p for p in keep.problems)


def test_every_real_default_resolves_to_weights():
    from harness import winners
    keep = disk.keepers(None, typed=winners.typed(), adopted={})
    assert keep.problems == []


def test_old_incomplete_blob_deleted_fresh_one_kept(world):
    d = make_repo(world.hub, "org/fetching")
    old = d / "blobs" / "old.incomplete"
    fresh = d / "blobs" / "fresh.incomplete"
    for p in (old, fresh):
        p.write_bytes(b"p" * 10)
    os.utime(old, (NOW - 2 * 3600, NOW - 2 * 3600))
    os.utime(fresh, (NOW - 600, NOW - 600))
    got = disk.clean(inv(world), NOW, world.conn)
    assert not old.exists() and fresh.exists()
    assert [r["path"] for r in got["incomplete"]] == [str(old)]


def test_cli_json_without_yes_deletes_nothing(world, monkeypatch, capsys):
    d = make_repo(world.hub, "org/bad")
    home = ms.connect()
    verdict(home, "org/bad", "broken", at=time.time() - 30 * DAY)
    home.close()
    rc = cli.main(["disk", "--delete", "unknown", "--json"])
    rc2 = cli.main(["disk", "--delete", "rejected", "--json"])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0 and rc2 == 1
    assert "--yes" in json.loads(out[-1])["error"]
    assert d.exists()
    assert cli.main(["disk", "--delete", "rejected", "--json", "--yes"]) == 0
    assert not d.exists()


def test_cli_without_a_tty_and_without_yes_deletes_nothing(world,
                                                          monkeypatch):
    d = make_repo(world.hub, "org/bad")
    home = ms.connect()
    verdict(home, "org/bad", "broken", at=time.time() - 30 * DAY)
    home.close()

    def no_tty(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", no_tty)
    assert cli.main(["disk", "--delete", "rejected"]) == 1
    assert d.exists()


def test_cli_inventory_groups_and_totals(world, capsys):
    make_repo(world.hub, "org/stray", size=2048)
    assert cli.main(["disk", "--json"]) == 0
    got = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert got["groups"]["unknown"] == {"count": 1, "bytes": 2048}


def test_the_loop_cleans_before_it_fetches(monkeypatch):
    order = []
    monkeypatch.setattr(disk, "sweep",
                        lambda *a, **k: order.append("sweep") or {})
    monkeypatch.setattr(cli, "cmd_fetch",
                        lambda a: order.append("fetch") or 0)
    monkeypatch.setattr(cli, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(cli, "measurable", lambda *a, **k: [])
    cli._loop_spend(argparse.Namespace(top=1, budget_gib=1.0, lane=""), 0)
    assert order == ["sweep", "fetch"]
