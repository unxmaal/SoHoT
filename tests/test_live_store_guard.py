"""Only the deploy checkout migrates the live store. #455."""
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

from harness import memory_store as ms
from harness import paths

REAL_LIVE = Path.home() / "localharness" / "discovery.db"
launchd_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the deploy checkout is a launchd.sh concept")


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    """A deploy checkout that is not this one."""
    d = tmp_path / "deploy"
    (d / ".git").mkdir(parents=True)
    monkeypatch.setenv("LH_DEPLOY", str(d))
    monkeypatch.delenv(paths.ALLOW_MIGRATE_ENV, raising=False)
    return d


@pytest.fixture
def live(tmp_path, monkeypatch, old_store, deploy):
    """A schema-13 store at the default home, with the default home moved to tmp."""
    monkeypatch.setattr(paths, "DEFAULT_HOME", tmp_path)
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    path = old_store(13, name="discovery.db")
    assert ms.db_path() == path and paths.is_live(path)
    assert not paths.is_live(REAL_LIVE)
    return path


def _schema(path):
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute(
            "SELECT value FROM meta WHERE key='schema'").fetchone()[0])
    finally:
        conn.close()


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@launchd_only
def test_a_live_store_behind_the_code_is_refused_from_another_checkout(live, deploy):
    before = _digest(live)
    with pytest.raises(ms.LiveStoreRefused) as err:
        ms.connect()
    msg = str(err.value)
    assert "launchd.sh install" in msg and paths.ENV_VAR in msg
    assert paths.ALLOW_MIGRATE_ENV in msg and str(deploy.resolve()) in msg
    assert _schema(live) == 13 and _digest(live) == before


@launchd_only
def test_an_absent_live_store_is_not_created_from_another_checkout(
        tmp_path, monkeypatch, deploy):
    monkeypatch.setattr(paths, "DEFAULT_HOME", tmp_path / "home")
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    with pytest.raises(ms.LiveStoreRefused):
        ms.connect()
    assert not ms.db_path().exists()


def test_the_deploy_checkout_migrates_the_live_store(live, monkeypatch):
    monkeypatch.setenv("LH_DEPLOY", str(paths.REPO))
    assert paths.runs_elsewhere() is None
    ms.connect().close()
    assert _schema(live) == ms.SCHEMA_VERSION


def test_the_override_migrates_the_live_store(live, monkeypatch):
    monkeypatch.setenv(paths.ALLOW_MIGRATE_ENV, "1")
    ms.connect().close()
    assert _schema(live) == ms.SCHEMA_VERSION


def test_a_machine_with_no_deploy_checkout_migrates_as_before(live, deploy):
    (deploy / ".git").rmdir()
    ms.connect().close()
    assert _schema(live) == ms.SCHEMA_VERSION


def test_a_newer_live_store_keeps_the_newer_store_refusal(live):
    conn = sqlite3.connect(live)
    conn.execute("UPDATE meta SET value = ? WHERE key='schema'",
                 (str(ms.SCHEMA_VERSION + 1),))
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="Refusing to touch a newer store") as err:
        ms.connect()
    assert not isinstance(err.value, ms.LiveStoreRefused)


def test_an_explicit_store_path_migrates_as_before(old_store, deploy):
    path = old_store(13)
    assert not paths.is_live(path)
    ms.connect(path).close()
    assert _schema(path) == ms.SCHEMA_VERSION


def test_a_non_default_home_migrates_as_before(tmp_path, monkeypatch, old_store,
                                               deploy):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    path = old_store(13, name="discovery.db")
    assert ms.db_path() == path and not paths.is_live(path)
    ms.connect().close()
    assert _schema(path) == ms.SCHEMA_VERSION


@launchd_only
def test_launchd_and_python_agree_on_where_the_deploy_is(tmp_path, monkeypatch):
    monkeypatch.delenv("LH_DEPLOY", raising=False)
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.deploy_checkout() == (tmp_path / "deploy").resolve()
