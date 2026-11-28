"""A deploy re-imports a source whose importer or manifest changed since its carried cases were written. #2194."""
from __future__ import annotations

import subprocess
import sys

import pytest

from harness import deploy, paths
from harness import workqueue as wq
from tests.test_deploy_1506 import _commit, _queue, _worker_runs, posix, world  # noqa: F401
from evals import importers

MODULE = "evals/importers/librispeech.py"
MANIFEST = "evals/importers/librispeech.jsonl"
# Stands in for `soh cases import <name>`: one case file per manifest line, a call line in the log.
REIMPORT = ("import sys,pathlib\n"
            "n=sys.argv[1]\n"
            "rows=pathlib.Path(f'evals/importers/{n}.jsonl').read_text().split()\n"
            "d=pathlib.Path('evals/cases/stt')/n\n"
            "d.mkdir(parents=True,exist_ok=True)\n"
            "[(d/f'{r}.yaml').write_text('imported\\n') for r in rows]\n")


def _deploy(world, files, tmp_path):
    called = tmp_path / "reimport-calls"
    code = REIMPORT + f"open({str(called)!r},'a').write(n+'\\n')\n"
    world["steps"].reimport = [sys.executable, "-c", code]
    job = _queue(world, files)
    _worker_runs(job, world)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.DEPLOYED]
    return called, world["link"] / "evals" / "cases" / "stt" / "librispeech"


def _carried(world, rows):
    _commit(world["work"], {MODULE: "LANE = 'stt'\n", MANIFEST: rows}, "importer")
    subprocess.run(["git", "-C", str(world["link"]), "pull", "-q", "origin", "main"], check=True)
    d = world["link"] / "evals" / "cases" / "stt" / "librispeech"
    d.mkdir(parents=True)
    (d / "a.yaml").write_text("imported\n", encoding="utf-8")


@pytest.mark.sqlite_store
@posix
def test_a_manifest_with_an_extra_line_is_re_imported_into_the_new_release(world, tmp_path):
    _carried(world, "a\n")
    called, out = _deploy(world, {MANIFEST: "a\nb\n"}, tmp_path)
    assert called.read_text(encoding="utf-8") == "librispeech\n"
    assert sorted(p.name for p in out.glob("*.yaml")) == ["a.yaml", "b.yaml"]
    log = (paths.logs() / "deploy.log").read_text(encoding="utf-8")
    assert "importer librispeech changed" in log and "re-imported librispeech" in log


@pytest.mark.sqlite_store
@posix
def test_an_unchanged_manifest_is_not_re_imported(world, tmp_path):
    _carried(world, "a\n")
    called, out = _deploy(world, {"unrelated": "x\n"}, tmp_path)
    assert not called.exists()
    assert [p.name for p in out.glob("*.yaml")] == ["a.yaml"]


def test_the_fingerprint_follows_the_importer_and_its_manifest(tmp_path):
    folder = tmp_path / "importers"
    folder.mkdir()
    (folder / "x.jsonl").write_text("a\n", encoding="utf-8")
    one = importers.fingerprint("x", folder)
    (folder / "x.jsonl").write_text("a\nb\n", encoding="utf-8")
    assert importers.fingerprint("x", folder) != one
    assert importers.fingerprint("y", folder) != importers.fingerprint("x", folder)
