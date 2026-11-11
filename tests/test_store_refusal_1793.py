"""A schema refusal is not an outage; in the live home only the deploy alerts or marks an outage, once per cause. #1793."""
import json
import sqlite3

import pytest

from harness import exclusive, monitor, paths
from harness import memory_store as ms
from harness.memory_store.schema import SCHEMA_VERSION

pytestmark = pytest.mark.sqlite_store

HOOK = "https://discord.invalid/api/webhooks/1793/token"
DOWN = "OperationalError"


@pytest.fixture(autouse=True)
def _unheld(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _live(tmp_path, monkeypatch, *, schema=SCHEMA_VERSION, deploy=True):
    """A live home whose store is at `schema`, seen from the deploy checkout or from another checkout."""
    home = tmp_path / "live"
    path = home / "discovery.db"
    ms.connect(path).close()
    if schema != SCHEMA_VERSION:
        conn = sqlite3.connect(path)
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(schema),))
        conn.commit()
        conn.close()
    monkeypatch.setattr(paths, "DEFAULT_HOME", home)
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: None if deploy else tmp_path / "deploy")
    monitor.env_path().write_text(f'export {monitor.WEBHOOK}="{HOOK}"\n', encoding="utf-8")
    assert monitor.live_home() and paths.is_live(ms.db_path())
    return path


def _down(monkeypatch):
    def refused(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")
    monkeypatch.setattr(exclusive, "_conn", refused)


def _refused(kind="eval"):
    with pytest.raises(exclusive.StoreDown) as got:
        with exclusive.held(kind):
            pytest.fail("ran with no gpu lease")
    return got.value


@pytest.mark.parametrize("schema, deploy", [(SCHEMA_VERSION - 1, False), (SCHEMA_VERSION + 1, True)],
                         ids=["schema-ahead-worktree", "old-release-mid-deploy"])
def test_a_schema_refusal_on_the_live_home_alerts_nothing_and_marks_nothing(
        tmp_path, monkeypatch, capsys, _no_real_notifier, schema, deploy):
    _live(tmp_path, monkeypatch, schema=schema, deploy=deploy)
    for kind in ("eval", "image"):
        got = _refused(kind)
        assert isinstance(got, exclusive.StoreSkewed) and "unreachable" not in str(got)
        assert "will not use" in str(got)
    assert _no_real_notifier == [] and not exclusive.refused_path().exists()
    assert not monitor.alerts_path().exists()
    assert capsys.readouterr().err.count("schema skew, not alerted") == 2


def test_a_real_outage_seen_by_the_deploy_alerts_once_and_names_its_writer(tmp_path, monkeypatch, _no_real_notifier):
    _live(tmp_path, monkeypatch)
    _down(monkeypatch)
    for kind in ("eval", "external", "image"):
        got = _refused(kind)
        assert not isinstance(got, exclusive.StoreSkewed) and "the store is unreachable" in str(got)
    assert [s[0] for s in _no_real_notifier] == ["desktop", "webhook"]
    assert "eval refused: the store is unreachable" in _no_real_notifier[0][2]
    mark = exclusive.refusal()
    assert (mark["who"], mark["writer"], mark["cause"]) == ("eval", str(paths.REPO), DOWN)


def test_a_real_outage_seen_from_another_checkout_on_the_live_home_is_left_to_the_deploy(
        tmp_path, monkeypatch, _no_real_notifier):
    _live(tmp_path, monkeypatch, deploy=False)
    _down(monkeypatch)
    assert "the store is unreachable" in str(_refused())
    assert _no_real_notifier == [] and not exclusive.refused_path().exists()


@pytest.mark.parametrize("planted", [
    {"who": "eval", "reason": "eval refused: the store is unreachable: written before #1793"},
    {"who": "eval", "writer": "<repo>", "cause": "LiveStoreRefused"},
    {"who": "eval", "writer": "/elsewhere/sohot-worktree", "cause": DOWN},
], ids=["no-writer", "other-cause", "other-writer"])
def test_a_standing_marker_never_hides_an_outage_from_another_cause_or_writer(
        tmp_path, monkeypatch, _no_real_notifier, planted):
    _live(tmp_path, monkeypatch)
    planted = {k: (str(paths.REPO) if v == "<repo>" else v) for k, v in planted.items()}
    exclusive.refused_path().write_text(json.dumps(planted), encoding="utf-8")
    _down(monkeypatch)
    _refused("image")
    _refused("eval")
    assert [s[0] for s in _no_real_notifier] == ["desktop", "webhook"]
    mark = exclusive.refusal()
    assert (mark["who"], mark["writer"], mark["cause"]) == ("image", str(paths.REPO), DOWN)


def test_only_the_deploy_ends_a_standing_refusal(tmp_path, monkeypatch, _no_real_notifier):
    _live(tmp_path, monkeypatch, deploy=False)
    exclusive.refused_path().write_text(json.dumps({"who": "eval", "writer": "/deploy", "cause": DOWN}),
                                        encoding="utf-8")
    assert exclusive.gpu_leases() == 0
    assert exclusive.refused_path().exists() and _no_real_notifier == []
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: None)
    assert exclusive.gpu_leases() == 0
    assert not exclusive.refused_path().exists()
    assert [s[0] for s in _no_real_notifier] == ["desktop", "webhook"] and "reachable again" in _no_real_notifier[0][2]
