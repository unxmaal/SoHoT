"""Gauntlet OR-8 rest (#1984): the mflux uv tool root is read under the home of the moment, not the home at import."""
from __future__ import annotations

from harness import engines, machine, stages
from tests.test_mflux_second_repo_1546 import ENCODER, VAE, fake_mflux


def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return fake_mflux(home / ".local" / "share" / "uv" / "tools" / "mflux")


def test_the_tool_root_follows_a_home_set_after_import(tmp_path, monkeypatch):
    root = _home(tmp_path, monkeypatch)
    assert stages.mflux_tool_root() == root


def test_mflux_repos_reads_the_tool_under_the_home_set_after_import(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert engines.mflux_repos("mflux-generate-lens") == (ENCODER, VAE)


def test_tool_versions_reads_the_tool_under_the_home_set_after_import(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    assert stages.tool_versions()["mflux"] == "9.9.9"


def test_the_installed_stamp_watches_the_tool_under_the_home_set_after_import(tmp_path, monkeypatch):
    root = _home(tmp_path, monkeypatch)
    site = root / "lib" / "python3.12" / "site-packages"
    assert str(site) in [entry[0] for entry in machine.installed_stamp()[:-1]]
