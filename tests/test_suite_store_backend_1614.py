"""The suite never takes its store backend from the developer's home store.json; only LOCALHARNESS_STORE picks Postgres (#1614)."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from harness import paths, store
from tests import conftest

INNER = '''
from harness import paths, store

COLLECTED = store.backend()


def test_the_session_backend_ignores_the_real_homes_store_json(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    assert store.marker(paths.DEFAULT_HOME).get("backend") == "postgres"
    assert (COLLECTED, store.backend()) == ("sqlite", "sqlite")
'''


def _session(tmp_path):
    real = Path(__file__).with_name("conftest.py")
    (tmp_path / "conftest.py").write_text(
        f"exec(compile(open({str(real)!r}).read(), {str(real)!r}, 'exec'))\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(INNER, encoding="utf-8")
    user = tmp_path / "user"
    (user / "localharness").mkdir(parents=True)
    (user / "localharness" / store.MARKER).write_text(json.dumps({"backend": "postgres"}), encoding="utf-8")
    clean = {k: v for k, v in os.environ.items()
             if k not in (store.BACKEND_ENV, paths.ENV_VAR, "PYTEST_ADDOPTS") and not k.startswith("PG")}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:randomly",
                           "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path / "test_inner.py")],
                          capture_output=True, text=True, cwd=Path(__file__).parents[1],
                          env={**clean, "HOME": str(user), "USERPROFILE": str(user)},
                          timeout=conftest.HANG_DUMP_S)


def test_a_postgres_store_json_in_the_real_home_still_runs_the_suite_on_sqlite(tmp_path):
    got = _session(tmp_path)
    assert got.returncode == 0, got.stdout[-2000:]
    assert "store backend: sqlite" in got.stdout


def test_an_explicit_backend_variable_is_left_alone(monkeypatch):
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    monkeypatch.setattr(conftest, "_test_log", {})
    conftest.pytest_configure(SimpleNamespace())
    assert os.environ[store.BACKEND_ENV] == store.POSTGRES
