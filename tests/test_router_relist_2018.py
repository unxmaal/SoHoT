"""A deploy relists the router's phantoms whose files are gone; relist expects only stems a restart lists. #2018."""
import re
from pathlib import Path

import pytest

from harness import cli, gguf, relist, router
from harness.commands import gguf_aux
from harness.commands import relist as relist_cmd
from tests.test_context import QWEN3_4B
from tests.test_gguf_aux_1674 import AUX, HEAD, blk, write
from tests.test_smoke_gguf_aux_1681 import DRAFTER, _smoke, _with_drafter, needs_bash, router as fake  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
#: The real one: conftest swaps the module attribute for a stub in every test.
REFRESH = gguf.refresh_router


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


def _model(where: Path, stem: str) -> Path:
    write(where / f"{stem}.gguf", QWEN3_4B, HEAD + blk(range(36)))
    return where / f"{stem}.gguf"


# --- 1. smoke relists once when every phantom's file is gone ---------------

@needs_bash
def test_smoke_relists_a_phantom_whose_file_was_removed_by_hand_and_passes(fake, tmp_path):
    _model(fake.models, "Model")
    _model(fake.models, "Gone-Q4_K_M")
    fake.snapshot()
    (fake.models / "Gone-Q4_K_M.gguf").unlink()
    got = _smoke(fake, tmp_path)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "PASS  router advertises only models with a file" in got.stdout
    assert "note  relisted: the router restarted for 1 removed and 0 unlisted" in got.stdout
    assert fake.state["restarts"] == 1 and gguf.removed() == [] and not gguf.pending()


@needs_bash
def test_without_the_relist_the_same_removal_fails_the_smoke(fake, tmp_path):
    """Control: the fake router keeps listing a removed file until it restarts, as llama-server does."""
    _model(fake.models, "Gone-Q4_K_M")
    fake.snapshot()
    (fake.models / "Gone-Q4_K_M.gguf").unlink()
    got = _smoke(fake, tmp_path, relist=False)
    assert got.returncode == 1 and "FAIL  router advertises models with no file" in got.stdout
    assert "phantom: Gone-Q4_K_M: preset: " in got.stdout and fake.state["restarts"] == 0


@needs_bash
def test_a_phantom_whose_file_is_still_in_the_models_dir_fails_without_a_restart(fake, tmp_path):
    _with_drafter(fake)
    got = _smoke(fake, tmp_path, repair=False)
    assert got.returncode == 1 and "FAIL  router advertises models with no file" in got.stdout
    assert f"note    {Path(DRAFTER).stem}: preset: no --model" in got.stdout
    assert "note  router relist: not restarting: 1 advertised id(s) keep a file in" in got.stdout
    assert fake.state["restarts"] == 0


def test_the_smoke_relist_default_is_the_router_relist_verb():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith("RELIST="))
    default = line.split(":-", 1)[1].rsplit("}", 1)[0].split()
    assert default[:6] == ["uv", "run", "--quiet", "python", "-m", "harness.cli"]
    assert cli.build_parser().parse_args(default[6:]).func is relist_cmd.cmd_relist


def test_the_phantom_fail_line_names_only_commands_that_exist():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "router advertises models with no file" in ln)
    named = re.findall(r"\\`(soh [^`\\]+)\\`", line)
    assert named == ["soh router relist", "soh gguf-aux --apply"]
    funcs = [cli.build_parser().parse_args(n.split()[1:]).func for n in named]
    assert funcs == [relist_cmd.cmd_relist, gguf_aux.cmd_gguf_aux]
    assert "restart the router;" not in text


# --- 2. relist expects only stems a restarted router lists -----------------

def test_relist_expects_only_model_files_in_the_dir_and_clears_both_files(models, monkeypatch, shown_live):
    meta, tensors, _ = AUX[DRAFTER]
    write(models / DRAFTER, meta, tensors)
    _model(models, "Real-Q4_K_M")
    gguf.note_unlisted([Path(DRAFTER).stem, "Deleted-Q4_K_M", "Real-Q4_K_M"])
    gguf.note_removed(["Gone"])
    asked = []

    def wait(expect):
        asked.append(expect)
        return "" if set(expect) <= {"Real-Q4_K_M"} else f"did not answer /health ok listing {', '.join(expect)}"
    monkeypatch.setattr(gguf, "refresh_router", lambda expect=(): REFRESH(expect, run=lambda *a, **k: None, wait=wait))
    assert gguf.unlisted() == ["Real-Q4_K_M"]
    assert gguf.relist() == ""
    assert asked == [("Real-Q4_K_M",)]
    assert not gguf._unlisted_path().exists() and not gguf._removed_path().exists()


def test_relist_with_only_stems_that_will_never_list_restarts_nothing_and_clears_them(models, _no_real_services):
    gguf.note_unlisted(["blk-00041", "Deleted-Q4_K_M"])
    assert gguf._unlisted_path().exists() and gguf.unlisted() == [] and not gguf.pending()
    assert gguf.relist() == ""
    assert _no_real_services == [] and not gguf._unlisted_path().exists()


def test_a_dangling_link_or_an_empty_stem_is_not_listable(models):
    (models / "Link-Q4_K_M.gguf").symlink_to(models / "nowhere.gguf")
    _model(models, "Real-Q4_K_M")
    assert gguf.listable(["", "Link-Q4_K_M", "Real-Q4_K_M"]) == ["Real-Q4_K_M"]
    assert gguf.listable(["Real-Q4_K_M"], where=models.parent) == []


# --- 3. `soh router relist` --------------------------------------------------

def test_gone_names_the_ids_with_no_file_of_their_name_in_the_dir(models):
    _model(models, "Here")
    found = {"Here": "x", "Gone": "y", "org/repo:Q4_K_M": "z"}
    assert relist.gone(found) == ["Gone", "org/repo:Q4_K_M"]
    assert relist.gone(found, where=models.parent) == ["Gone", "Here", "org/repo:Q4_K_M"]


def test_relist_notes_the_gone_ids_and_restarts_once(models, _no_real_services):
    said = []
    assert relist.run({"Gone": "preset: gone"}, say=said.append) == ""
    assert _no_real_services == [()] and gguf.removed() == []
    assert said == ["relisted: the router restarted for 1 removed and 0 unlisted"]
    assert relist.run({}, say=said.append) == "" and said[-1] == "nothing to relist"
    assert _no_real_services == [()]


def test_relist_keeps_the_router_when_a_phantom_keeps_its_file(models, _no_real_services):
    _model(models, "Held")
    said = []
    why = relist.run({"Held": "preset: no --model", "Gone": "preset: gone"}, say=said.append)
    assert why == (f"not restarting: 1 advertised id(s) keep a file in {models}, which a restart lists again; "
                   f"`{gguf.REPAIR}` sets auxiliary ones aside")
    assert said == ["  Held: preset: no --model"]
    assert _no_real_services == [] and gguf.removed() == ["Gone"]


def test_a_failed_restart_is_the_verbs_failure(models, monkeypatch):
    monkeypatch.setattr(gguf, "refresh_router", lambda expect=(): "did not answer")
    assert relist.run({"Gone": "x"}, say=lambda m: None) == "did not answer"
    assert gguf.removed() == ["Gone"]


def test_the_verb_relists_what_the_router_lists_with_no_file(models, monkeypatch, capsys, _no_real_services):
    monkeypatch.setattr(router, "phantoms", lambda get=None: {"Gone": "preset: gone"})
    assert cli.main(["router", "relist"]) == 0
    assert capsys.readouterr().out == "relisted: the router restarted for 1 removed and 0 unlisted\n"
    assert _no_real_services == [()]


def test_the_verb_fails_when_the_router_does_not_answer(monkeypatch, capsys, _no_real_services):
    monkeypatch.setattr(router, "phantoms", lambda get=None: None)
    assert cli.main(["router", "relist"]) == 1
    assert "did not answer GET /models" in capsys.readouterr().err and _no_real_services == []


def test_the_verb_fails_when_a_phantom_keeps_its_file(models, monkeypatch, capsys, _no_real_services):
    _model(models, "Held")
    monkeypatch.setattr(router, "phantoms", lambda get=None: {"Held": "preset: no --model"})
    assert cli.main(["router", "relist"]) == 1
    got = capsys.readouterr()
    assert got.out == "  Held: preset: no --model\n" and "router relist: not restarting" in got.err
    assert _no_real_services == []
