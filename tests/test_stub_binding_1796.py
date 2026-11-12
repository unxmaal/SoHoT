"""A stub installed after import reaches every call path that leaves the effect out: no effect is a default argument. #1796."""
import contextlib
import io
import subprocess
import urllib.request

import pytest

from gauntlet import scanners as gscanners

from harness import ci_history, ci_rerun, claude_news, deploy_guard, inspect, monitor, morning, publish, sweep_guard
from tests.gauntlet import scanners
from tests.test_gauntlet_scanners import REPO, _fail_with

DEAD = "http://127.0.0.1:9/"


class Reached(Exception):
    pass


def _real_effects_refused(monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError(f"a real effect ran: {a[:1]}")
    monkeypatch.setattr(subprocess, "run", refuse)


def _deploy_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


SITES = {
    "deploy_guard.check gh": (deploy_guard, "_gh", lambda tmp: deploy_guard.check("a" * 40, environ={}, err=io.StringIO())),
    "deploy_guard.twin git": (deploy_guard, "_git", lambda tmp: deploy_guard.twin("a" * 40, gh=lambda *a, **k: "[]")),
    "morning.ci gh": (morning, "_gh", lambda tmp: morning.ci(0.0)),
    "morning.deploy git": (morning, "_git", lambda tmp: morning.deploy(_deploy_checkout(tmp))),
    "ci_history.collect gh": (ci_history, "_gh", lambda tmp: ci_history.collect(1, tmp / "cache")),
    "ci_rerun.main gh": (ci_rerun, "_gh", lambda tmp: ci_rerun.main(["1"], environ={})),
    "inspect.clone run": (inspect, "_run", lambda tmp: inspect.clone("o/r", tmp / "src")),
    "publish.publish_here gh": (publish, "_gh", lambda tmp: publish.publish_here(repo="o/r")),
    "claude_news.fetch urlopen": (urllib.request, "urlopen", lambda tmp: claude_news.fetch(DEAD)),
    "monitor.post urlopen": (urllib.request, "urlopen", lambda tmp: monitor.post.real("t", DEAD)),
    "monitor.du Popen": (subprocess, "Popen", lambda tmp: monitor.du([("x", tmp)], 5.0)),
    "sweep_guard.stop kill": (__import__("os"), "kill",
                              lambda tmp: sweep_guard.stop([{"pid": 999_999_999}], grace=0.0, alive=lambda pid: False)),
}


@pytest.mark.parametrize("site", sorted(SITES))
def test_a_stub_installed_after_import_reaches_a_call_that_leaves_the_effect_out(site, monkeypatch, tmp_path):
    owner, name, call = SITES[site]
    _real_effects_refused(monkeypatch)
    calls = []

    def stub(*a, **k):
        calls.append(a[:1])
        raise Reached(site)
    monkeypatch.setattr(owner, name, stub)
    with contextlib.suppress(Exception):
        call(tmp_path)
    assert calls, f"{site}: the stub of {name} never ran; the call reached the effect bound when the module loaded"


CONFTEST = ("import subprocess\nimport pytest\nfrom harness import monitor\n\n"
            "@pytest.fixture(autouse=True)\ndef _guard(monkeypatch):\n"
            "    from harness import engine_trials as et\n"
            "    monkeypatch.setattr(subprocess, \"Popen\", object)\n"
            "    monkeypatch.setattr(monitor, \"desktop\", object)\n"
            "    for name in (\"gh_run\", \"ask_model\"):\n"
            "        monkeypatch.setattr(et, name, object)\n\n"
            "@pytest.fixture\ndef opt_in(monkeypatch):\n    monkeypatch.setattr(monitor, \"post\", object)\n")


def test_the_stubs_are_read_from_conftests_autouse_fixtures():
    assert scanners.conftest_stubs(CONFTEST) == {("subprocess", "Popen"), ("harness.monitor", "desktop"),
                                                 ("harness.engine_trials", "gh_run"),
                                                 ("harness.engine_trials", "ask_model")}


STUBS = scanners.conftest_stubs(CONFTEST)


@pytest.mark.parametrize("bad,rel", [
    ("from subprocess import Popen\n", "harness/x.py"),
    ("from harness.monitor import desktop as d\n", "harness/x.py"),
    ("try:\n    from harness.engine_trials import gh_run\nexcept ImportError:\n    pass\n", "harness/x.py"),
    ("import subprocess\ndef f(popen=subprocess.Popen):\n    return popen\n", "harness/x.py"),
    ("from harness import monitor\ndef f(*, notify=monitor.desktop):\n    return notify\n", "harness/x.py"),
    ("def desktop():\n    pass\ndef alert(notify=desktop):\n    return notify\n", "harness/monitor.py"),
    ("from harness import engine_trials as et\ndef f(ask=et.ask_model):\n    return ask\n", "harness/x.py"),
])
def test_a_stubbed_name_bound_before_the_stub_is_found(bad, rel):
    assert len(scanners.stub_bindings(bad, rel, STUBS)) == 1, bad


def test_a_stubbed_name_read_at_call_time_is_left_alone():
    innocent = ("import subprocess\nfrom harness import monitor\nfrom subprocess import PIPE\n"
                "def f(popen=None, notify=None):\n"
                "    from harness.engine_trials import gh_run\n"
                "    popen = popen or subprocess.Popen\n"
                "    return (notify or monitor.desktop)(gh_run, popen)\n"
                "def g(run=subprocess.run):\n    return run\n")
    assert scanners.stub_bindings(innocent, "harness/x.py", STUBS) == []
    assert scanners.stub_bindings("def alert(notify=desktop):\n    pass\n", "harness/x.py", STUBS) == []


def test_no_production_code_binds_a_conftest_stub_before_it_is_installed():
    _fail_with(gscanners.scan_tree(REPO, scanners.stub_bindings, gscanners.is_python,
                                   lambda rel: not rel.startswith("tests/")),
               "conftest replaces this name for every test, but this binding took the real one when the module "
               "loaded; default to None and resolve it at call time, or import the module and read module.name (#1796)")


def test_the_live_conftest_stubs_are_found():
    found = scanners.conftest_stubs()
    assert {("subprocess", "Popen"), ("harness.monitor", "desktop"), ("harness.engine_trials", "gh_run"),
            ("harness.runtime_trials", "_run"), ("harness.memory_store.machines", "_THIS_MACHINE")} <= found
