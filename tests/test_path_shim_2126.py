"""scripts/path-shim.sh: soh and lh on PATH run the live release through the deploy link (#2126)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import shells

REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "scripts" / "path-shim.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the shims are for the unix machines")


def _release(home: Path, name: str, says: str) -> Path:
    rel = home / "localharness" / "releases" / name
    exe = rel / ".venv" / "bin" / "soh"
    exe.parent.mkdir(parents=True)
    exe.write_text(f'#!/bin/sh\n[ "$1" = --help ] && echo "{says}" && exit 0\necho "{says} $*"\n', encoding="utf-8")
    exe.chmod(0o755)
    return rel


def _link(home: Path, rel: Path) -> None:
    link = home / "localharness" / "deploy"
    tmp = link.with_name("deploy.new")
    tmp.symlink_to(rel)
    os.replace(tmp, link)


def _run(home: Path, *args: str):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    return subprocess.run([shells.BASH, str(SHIM), *args], env=env, capture_output=True, text=True)


def _call(home: Path, name: str) -> str:
    out = subprocess.run([str(home / ".local" / "bin" / name), "x"], capture_output=True, text=True)
    return out.stdout.strip() + out.stderr.strip()


def test_install_writes_shims_that_run_the_deploy_link(tmp_path):
    _link(tmp_path, _release(tmp_path, "1-aaa", "one"))
    got = _run(tmp_path, "install")
    assert got.returncode == 0, got.stderr
    assert _call(tmp_path, "soh") == "one x"
    assert _call(tmp_path, "lh") == "one x"


def test_reinstall_is_a_noop(tmp_path):
    _link(tmp_path, _release(tmp_path, "1-aaa", "one"))
    _run(tmp_path, "install")
    shim = tmp_path / ".local" / "bin" / "soh"
    before = (shim.read_text(encoding="utf-8"), shim.stat().st_ino)
    got = _run(tmp_path, "install")
    assert got.returncode == 0 and "unchanged" in got.stdout and "wrote" not in got.stdout
    assert (shim.read_text(encoding="utf-8"), shim.stat().st_ino) == before


def test_foreign_file_is_left_alone_and_reported(tmp_path):
    _link(tmp_path, _release(tmp_path, "1-aaa", "one"))
    bin_dir = tmp_path / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "lh").symlink_to(tmp_path / "gone")
    (bin_dir / "soh").write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    got = _run(tmp_path, "install")
    assert got.returncode == 1
    assert got.stderr.count("REFUSED") == 2 and "not ours" in got.stderr
    assert (bin_dir / "lh").is_symlink() and os.readlink(bin_dir / "lh") == str(tmp_path / "gone")
    assert (bin_dir / "soh").read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"


def test_shim_follows_a_switch_and_a_rollback(tmp_path):
    first, second = _release(tmp_path, "1-aaa", "one"), _release(tmp_path, "2-bbb", "two")
    _link(tmp_path, first)
    _run(tmp_path, "install")
    _link(tmp_path, second)
    assert _call(tmp_path, "soh") == "two x"
    _link(tmp_path, first)
    assert _call(tmp_path, "lh") == "one x"


def test_check_passes_on_a_good_shim(tmp_path):
    _link(tmp_path, _release(tmp_path, "1-aaa", "one"))
    _run(tmp_path, "install")
    got = _run(tmp_path, "check")
    assert got.returncode == 0, got.stdout
    assert "PASS  soh" in got.stdout


def test_check_fails_loudly_when_the_deploy_tree_is_missing(tmp_path):
    rel = _release(tmp_path, "1-aaa", "one")
    _link(tmp_path, rel)
    _run(tmp_path, "install")
    (rel / ".venv" / "bin" / "soh").unlink()
    got = _run(tmp_path, "check")
    assert got.returncode == 1
    assert "FAIL  soh" in got.stdout and "is missing" in got.stdout


def test_check_fails_when_soh_is_absent(tmp_path):
    got = _run(tmp_path, "check")
    assert got.returncode == 1 and "FAIL  soh" in got.stdout


def test_a_broken_lh_is_a_warning_not_a_failure(tmp_path):
    _link(tmp_path, _release(tmp_path, "1-aaa", "one"))
    _run(tmp_path, "install")
    lh = tmp_path / ".local" / "bin" / "lh"
    lh.unlink()
    lh.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    lh.chmod(0o755)
    got = _run(tmp_path, "check")
    assert got.returncode == 0 and "WARN  lh" in got.stdout


def test_install_and_smoke_are_wired_to_the_shim():
    launchd = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert launchd.index("path-shim.sh\" install") < launchd.index('[ "${1:-}" = reinstall ] || _record_install_env')
    assert "path-shim.sh check" in (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
