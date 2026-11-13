"""`soh --scratch-home DIR` binds a hand-set scratch home to the machine home, as paths.eval_home does. #1867."""
import os

import pytest

from harness import cli, delegate, interactive, local_tools, paths, router, serving, store
from tests.conftest import store_state, unset
from tests.test_scratch_home_serving_1711 import ORNITH, URL, _files, _plan


@pytest.fixture
def machine(monkeypatch):
    """The machine's home with its interactive plan, before any scratch home is named."""
    unset(monkeypatch, paths.MACHINE_FOR_ENV, paths.MACHINE_STORE_ENV)
    monkeypatch.delenv(interactive.KEY_ENV, raising=False)
    interactive.write(_plan())
    monkeypatch.setattr(router, "statuses", lambda get=None, base="": (
        {ORNITH: "loaded"} if serving.bare(base) == URL else {}))
    return paths.home()


def _soh(monkeypatch, *argv):
    """Run soh with `local complete`'s answer stood in by the route it would take."""
    seen = {}

    def complete(prompt, lane, *a, **kw):
        spec, where = delegate.route(lane or "code")
        seen.update(home=paths.home(), machine=paths.machine_home(), base=where.base, model=where.model)
        return {"call_id": "local-x", "text": "ok", "model": where.model, "seconds": 0.1}

    monkeypatch.setattr(local_tools, "complete", complete)
    monkeypatch.setattr("harness.delegations.instruction", lambda call_id, cli=False: "")
    return cli.main([*argv, "local", "complete", "hi", "--lane", "code"]), seen


def test_a_hand_set_scratch_home_with_the_switch_reaches_the_machine_s_interactive_server(machine, tmp_path,
                                                                                          monkeypatch):
    monkeypatch.chdir(tmp_path)
    before, files = store_state(machine / "discovery.db"), _files(machine)
    rc, seen = _soh(monkeypatch, "--scratch-home", "tmp/1867/home")
    scratch = (tmp_path / "tmp" / "1867" / "home").resolve()
    assert rc == 0
    assert (seen["home"], seen["machine"]) == (scratch, machine.resolve())
    assert (seen["base"], seen["model"]) == (URL, ORNITH), "answered by the machine's interactive server"
    assert os.environ[paths.MACHINE_FOR_ENV] == str(scratch), "a child the verb spawns stays bound"
    assert os.environ[store.BACKEND_ENV] == store.SQLITE
    assert store_state(machine / "discovery.db") == before and _files(machine) == files, "nothing written there"


def test_a_hand_set_scratch_home_without_the_switch_misses_the_interactive_server(machine, tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "scratch"))
    rc, seen = _soh(monkeypatch)
    assert rc == 0 and seen["machine"] == seen["home"] == (tmp_path / "scratch").resolve()
    assert seen["base"] != URL


def test_the_switch_refuses_the_machine_home_itself(machine, monkeypatch, capsys):
    rc, seen = _soh(monkeypatch, "--scratch-home", str(machine))
    assert rc != 0 and not seen and "not a scratch one" in capsys.readouterr().err
    assert paths.MACHINE_FOR_ENV not in os.environ


def test_the_switch_refuses_the_live_home(machine, monkeypatch, capsys):
    rc, seen = _soh(monkeypatch, "--scratch-home", str(paths.DEFAULT_HOME))
    assert rc != 0 and not seen and "live home" in capsys.readouterr().err
    assert paths.MACHINE_FOR_ENV not in os.environ


def test_a_scratch_home_s_store_is_its_own_sqlite_file_and_remembers_the_machine_s(machine, tmp_path, monkeypatch):
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    paths.scratch_home(tmp_path / "scratch")
    assert os.environ[store.BACKEND_ENV] == store.SQLITE
    assert os.environ[paths.MACHINE_STORE_ENV] == store.POSTGRES
