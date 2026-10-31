"""A local make check failure leaves a record the dead-weight inventory reads as a catch. #1261."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from harness import inventory_weight as iw, local_catches, paths
from tests import conftest

REPO = Path(__file__).resolve().parents[1]
DAY = 86400

PLANTED = '''
import pytest

def test_planted_catch():
    assert False, "planted"

@pytest.mark.parametrize("host", ["studio.example"])
def test_planted_param(host):
    assert False

def test_passes():
    import os
    assert "SOHOT_CATCHES" not in os.environ, "a pytest this test starts would record too"
'''


def _child(tmp_path, **env):
    home = tmp_path / "home"
    real = REPO / "tests" / "conftest.py"
    (tmp_path / "conftest.py").write_text(
        f"exec(compile(open({str(real)!r}).read(), {str(real)!r}, 'exec'))\n", encoding="utf-8")
    (tmp_path / "test_planted.py").write_text(PLANTED, encoding="utf-8")
    run_env = {k: v for k, v in os.environ.items() if k not in ("CI", "PYTEST_ADDOPTS", local_catches.ENV)}
    run_env.update({paths.ENV_VAR: str(home), **env})
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-p", "no:cacheprovider",
                          "-o", "addopts=", "--rootdir", str(tmp_path), str(tmp_path / "test_planted.py")],
                         capture_output=True, text=True, cwd=REPO, env=run_env, timeout=conftest.HANG_DUMP_S)
    assert got.returncode == 1, got.stdout[-2000:]
    return home / local_catches.FILE


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_test_that_fails_in_a_make_check_run_is_recorded_with_its_commit(tmp_path):
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    got = _lines(_child(tmp_path, **{local_catches.ENV: "1"}))
    assert len(got) == 1, got
    line = got[0]
    assert line["head"] == head and re.fullmatch(r"[0-9a-f]{40}", head)
    assert line["failed"] == ["test_planted.py::test_planted_catch", "test_planted.py::test_planted_param"]
    assert line["tests"] == 3 and line["exit"] == 1 and abs(line["at"] - __import__("time").time()) < 600


def test_a_run_under_ci_records_nothing_locally(tmp_path):
    assert _lines(_child(tmp_path, **{local_catches.ENV: "1", "CI": "true"})) == []


def test_a_run_outside_make_check_records_nothing(tmp_path):
    assert _lines(_child(tmp_path)) == []


def test_the_record_names_no_path_parameter_or_person(tmp_path):
    p = tmp_path / local_catches.FILE
    local_catches.record(p, "a" * 40, 5, 1, [
        "tests/test_x.py::test_y[studio.example-8890]", "tests/test_x.py::TestK::test_z",
        str(tmp_path / "test_abs.py") + "::test_w", "../elsewhere/test_v.py::test_v"])
    text = p.read_text(encoding="utf-8")
    line = json.loads(text)
    assert line["failed"] == ["tests/test_x.py::TestK.test_z", "tests/test_x.py::test_y"]
    assert line["other"] == 2, "a failure outside the repo's tests is counted, never named"
    assert set(line) == {"at", "head", "tests", "exit", "failed", "other"}
    for leak in ("studio", str(tmp_path), "elsewhere", os.path.expanduser("~")):
        assert leak not in text, leak


def _local(tmp_path, failed, at=DAY):
    p = tmp_path / local_catches.FILE
    p.write_text(json.dumps({"at": at, "head": "b" * 40, "tests": 9, "exit": 1, "failed": failed}) + "\n"
                 + json.dumps({"at": at, "head": "c" * 40, "tests": 9, "exit": 0, "failed": []}) + "\n"
                 + "not json\n", encoding="utf-8")
    return local_catches.read(p, since=0)


def test_a_test_recorded_as_a_local_catch_is_load_bearing_in_the_inventory(tmp_path):
    key = "tests/test_b.py::test_once_broke"
    local = _local(tmp_path, [key])
    assert local["runs"] == 2 and local["unreadable"] == 1 and len(local["failures"]) == 1
    L = iw.build({"now": 2 * DAY, "since": 0, "ci": {"runs": [], "failures": []}, "local": local,
                  "junit": {key: 20.0, "tests/test_a.py::test_slow": 9.0}})
    rows = {r["name"]: r for r in L["kinds"]["tests"]["rows"]}
    assert rows[key]["load_bearing"] and not rows[key]["flagged"] and rows[key]["rank"] == 0
    assert "1 local make check" in rows[key]["work"] and "local" in rows[key]["why"]
    assert not rows["tests/test_a.py::test_slow"]["load_bearing"]
    assert "never failed in CI or a local make check" in rows["tests/test_a.py::test_slow"]["work"]
    out = iw.render(L)
    assert "local make check: 2 run(s) recorded, 1 failed" in out and "1 unreadable" in out


def test_a_local_catch_outside_the_window_is_not_counted(tmp_path):
    p = tmp_path / local_catches.FILE
    p.write_text(json.dumps({"at": 10, "head": "b" * 40, "tests": 9, "exit": 1, "failed": ["tests/t.py::t"]}) + "\n",
                 encoding="utf-8")
    assert local_catches.read(p, since=100) == {"runs": 0, "failures": [], "unreadable": 0}
    assert local_catches.read(tmp_path / "absent.jsonl", since=0) == {"runs": 0, "failures": [], "unreadable": 0}


def test_a_scanner_recorded_as_a_local_catch_has_fired(tmp_path, monkeypatch):
    scanner = "tests/test_portability.py::test_no_text_file_is_read_or_written_without_an_explicit_encoding"
    local = _local(tmp_path, [scanner])
    checks = {"rows": [{"family": "scanner", "name": scanner, "class": ["a-platform-primitive"], "instances": 3},
                       {"family": "scanner", "name": "tests/test_q.py::test_idle", "class": ["x"], "instances": 1}]}
    L = iw.build({"now": 2 * DAY, "since": 0, "ci": {"runs": [{}] * 40, "failures": []}, "local": local,
                  "checks": checks})
    rows = {r["name"]: r for r in L["kinds"]["checks"]["rows"]}
    assert rows[scanner]["load_bearing"] and "fired 1 time(s), 1 in a local make check" in rows[scanner]["work"]
    assert rows["tests/test_q.py::test_idle"]["cost"] == 42, "local runs are evaluations too"
    assert not rows["tests/test_q.py::test_idle"]["load_bearing"]


def test_the_make_test_target_sets_the_variable_conftest_reads():
    make = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = re.search(r"^test:.*\n((?:\t.*\n)+)", make, re.M).group(1)
    assert f"{local_catches.ENV}=1 " in recipe and "pytest tests/" in recipe
    conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "local_catches.ENV" in conftest and "local_catches.ENV" not in recipe


def test_the_inventory_reads_the_record_from_the_home_it_was_given(tmp_path, monkeypatch):
    home = tmp_path / "h"
    home.mkdir()
    (home / local_catches.FILE).write_text(json.dumps(
        {"at": DAY, "head": "b" * 40, "tests": 9, "exit": 1, "failed": ["tests/t.py::t"]}) + "\n", encoding="utf-8")
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE machines (first_seen REAL)")
    monkeypatch.setattr(iw, "git_history", lambda run, root: [])
    monkeypatch.setattr(iw, "gather_knobs", lambda *a: [])
    src = iw.gather(conn, home, now=2 * DAY, since=0, kinds=("knobs",), ci=False)
    assert "local" not in src, "kinds that never read catches do not read the file"
    monkeypatch.setattr(iw, "gather_checks", lambda *a: {"rows": []})
    monkeypatch.setattr(iw, "gather_units", lambda *a: [])
    src = iw.gather(conn, home, now=2 * DAY, since=0, kinds=("checks",), ci=False)
    assert src["local"]["runs"] == 1 and src["local"]["failures"][0]["failed"] == ["tests/t.py::t"]
