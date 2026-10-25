"""The router advertises only stems with a file in its models dir; a delete under a running router restarts it. #780."""
import configparser
import subprocess
import sys
from pathlib import Path

import pytest

from harness import context, disk, downloads, gguf, router
from harness import memory_store as ms
from tests.test_context import GIB, ORNITH, write_gguf
from tests.test_harness_disk import NOW, entry, inv, remember, verdict, world  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
#: The real one: conftest swaps the module attribute for a stub in every test.
REFRESH = gguf.refresh_router


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _sections(conn) -> set:
    text = context.preset_text(context.plan(conn, budget=60 * GIB), 16384, 1)
    ini = configparser.ConfigParser()
    ini.read_string(text.split("\n", 1)[1])
    return set(ini.sections()) - {"*"}


def _row(conn, path):
    downloads.record(conn, "org/m", downloads.GGUF, path, file=path.name)


# --- 1. a preset section only for a stem the router can load ------------------

def test_a_row_whose_gguf_is_absent_produces_no_preset_section(conn, models):
    write_gguf(models / "Here.gguf", ORNITH)
    _row(conn, models / "Here.gguf")
    _row(conn, models / "Gone.gguf")
    assert _sections(conn) == {"Here"}


def test_a_row_whose_gguf_is_outside_the_models_dir_produces_no_preset_section(conn, models, tmp_path):
    elsewhere = tmp_path / "old-hf-home" / "gguf"
    elsewhere.mkdir(parents=True)
    write_gguf(elsewhere / "Moved.gguf", ORNITH)
    _row(conn, elsewhere / "Moved.gguf")
    write_gguf(models / "Here.gguf", ORNITH)
    _row(conn, models / "Here.gguf")
    assert _sections(conn) == {"Here"}
    assert context.router_bytes(conn) == context._weights(models / "Here.gguf") + \
        int(context.served(conn, "Here")["ctx"]) * int(context.served(conn, "Here")["kv_bytes_token"])


def test_a_symlink_in_the_models_dir_to_a_file_elsewhere_keeps_its_section(conn, models, tmp_path):
    blob = tmp_path / "hub" / "Linked.gguf"
    blob.parent.mkdir()
    write_gguf(blob, ORNITH)
    (models / "Linked.gguf").symlink_to(blob)
    _row(conn, models / "Linked.gguf")
    assert _sections(conn) == {"Linked"}


# --- 2. a delete under a running router restarts it once ----------------------

def test_deleting_a_gguf_from_the_models_dir_notes_it_for_the_router(world):  # noqa: F811
    path = world.gguf / "other.gguf"
    path.write_bytes(b"x" * 100)
    remember("org/other-GGUF", downloads.GGUF, path, file="other.gguf")
    verdict(world.conn, "org/other-GGUF", "broken", at=NOW - 30 * 24 * 3600)
    i = inv(world, typed={})
    assert entry(i, "other.gguf").group == disk.REJECTED
    disk.delete(i, NOW, disk.REJECTED, world.conn)
    assert not path.exists()
    assert gguf.removed() == ["other"] and gguf.pending()


def test_deleting_a_hub_repo_notes_the_repo_and_its_gguf_link(world):  # noqa: F811
    from tests.test_harness_disk import make_repo
    d = make_repo(world.hub, "org/thing-GGUF")
    (d / "snapshots" / "main" / "thing-Q4_K_M.gguf").symlink_to(d / "blobs" / "abc")
    (world.gguf / "thing.gguf").symlink_to(d / "blobs" / "abc")
    make_repo(world.hub, "org/weights")
    for name in ("org/thing-GGUF", "org/weights"):
        verdict(world.conn, name, "broken", at=NOW - 2 * 24 * 3600)
    got = disk.delete(inv(world), NOW, disk.REJECTED, world.conn)
    assert sorted(r["repo"] for r in got) == ["org/thing-GGUF", "org/weights"]
    assert gguf.removed() == ["org/thing-GGUF", "thing"]


def test_nothing_deleted_notes_nothing(world):  # noqa: F811
    disk.delete(inv(world), NOW, disk.REJECTED, world.conn)
    assert gguf.removed() == [] and not gguf.pending()


def test_relist_restarts_once_for_removed_stems_and_clears_them(_no_real_services):
    gguf.note_removed(["Gone"])
    assert gguf.pending()
    assert gguf.relist() == ""
    assert _no_real_services == [()]
    assert gguf.removed() == [] and not gguf.pending()
    assert gguf.relist() == "" and _no_real_services == [()]


def test_a_failed_restart_keeps_the_removed_stems(monkeypatch):
    monkeypatch.setattr(gguf, "refresh_router", lambda expect=(): "did not answer")
    gguf.note_removed(["Gone"])
    assert gguf.relist() == "did not answer"
    assert gguf.removed() == ["Gone"]


def test_any_restart_that_answers_clears_the_removed_stems_and_one_that_does_not_keeps_them():
    gguf.note_removed(["Gone"])
    assert REFRESH(run=lambda *a, **k: None, wait=lambda expect: "did not answer") == "did not answer"
    assert gguf.removed() == ["Gone"]
    assert REFRESH(run=lambda *a, **k: None, wait=lambda expect: "") == ""
    assert gguf.removed() == []


def test_the_loop_restarts_for_what_is_pending_not_only_unlisted():
    src = (ROOT / "harness" / "commands" / "loop.py").read_text(encoding="utf-8")
    assert "gguf.pending()" in src and "if gguf.unlisted():" not in src


# --- 3. anyone can ask which advertised ids have no file ----------------------

def _listing(*entries):
    def get(path):
        assert path == "/models"
        return {"data": [{"id": i, "source": s, "status": st if isinstance(st, str) else {"value": "unloaded", "args": st}}
                         for i, s, st in entries]}
    return get


def test_phantoms_names_each_advertised_id_with_no_file(tmp_path, monkeypatch):
    hub = tmp_path / "hf" / "hub"
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    snap = hub / "models--org--kept-GGUF" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "kept-Q8_0.gguf").write_bytes(b"x")
    real = tmp_path / "Real.gguf"
    real.write_bytes(b"x")
    get = _listing(
        ("Unknown", "models_dir", "unloaded"),
        ("NoArgs", "models_dir", []),
        ("Real", "preset", ["llama-server", "--model", str(real)]),
        ("Ghost", "preset", ["llama-server", "--alias", "Ghost", "--ctx-size", "2048"]),
        ("Trailing", "preset", ["llama-server", "--model"]),
        ("Removed", "models_dir", ["llama-server", "--model", str(tmp_path / "Removed.gguf")]),
        ("org/kept-GGUF:Q8_0", "cache", ["llama-server", "--hf-repo", "org/kept-GGUF:Q8_0"]),
        ("org/kept-GGUF", "cache", ["llama-server", "--hf-repo", "org/kept-GGUF"]),
        ("org/kept-GGUF:Q4_K_M", "cache", ["llama-server", "--hf-repo", "org/kept-GGUF:Q4_K_M"]),
        ("org/gone-GGUF:Q8_0", "cache", ["llama-server", "--hf-repo", "org/gone-GGUF:Q8_0"]),
    )
    got = router.phantoms(get)
    assert got == {
        "Ghost": "preset: no --model, a preset section with no file",
        "Trailing": "preset: no --model, a preset section with no file",
        "Removed": f"models_dir: {tmp_path / 'Removed.gguf'} is not on disk",
        "org/kept-GGUF:Q4_K_M": "cache: no org/kept-GGUF:Q4_K_M GGUF in the hub cache",
        "org/gone-GGUF:Q8_0": "cache: no org/gone-GGUF:Q8_0 GGUF in the hub cache",
    }


def test_phantoms_asks_this_machines_router_by_default(monkeypatch):
    asked = []
    monkeypatch.setattr(router, "_get", lambda path: asked.append(path) or {"data": []})
    assert router.phantoms() == {} and asked == ["/models"]


def test_phantoms_is_none_when_the_router_cannot_be_asked():
    def down(path):
        raise OSError("refused")
    assert router.phantoms(down) is None


def test_the_phantoms_command_exits_nonzero_naming_them(monkeypatch, capsys):
    monkeypatch.setattr(router, "phantoms", lambda get=None: {"Ghost": "no --model"})
    assert router.main(["phantoms"]) == 1
    assert capsys.readouterr().out == "phantom: Ghost: no --model\n"
    monkeypatch.setattr(router, "phantoms", lambda get=None: {})
    monkeypatch.setattr(sys, "argv", ["harness.router", "phantoms"])
    assert router.main() == 0
    assert capsys.readouterr() == ("", "")
    monkeypatch.setattr(router, "phantoms", lambda get=None: None)
    assert router.main(["phantoms"]) == 2
    out, err = capsys.readouterr()
    assert out == "" and err == f"router at {router.url()} did not answer GET /models\n"


def test_the_phantoms_command_refuses_anything_else(capsys):
    assert router.main(["nonsense"]) == 2
    assert capsys.readouterr() == ("", "usage: python -m harness.router phantoms\n")


def test_the_phantoms_command_runs_as_a_module():
    got = subprocess.run([sys.executable, "-m", "harness.router", "nonsense"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 2 and "usage" in got.stderr


def test_smoke_checks_the_router_for_phantoms():
    src = (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    assert "python -m harness.router phantoms" in src
