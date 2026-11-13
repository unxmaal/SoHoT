"""On Windows a path inside the old release is found with either separator and in any case, and named at the same place in the new one. #1919."""
import sys
from pathlib import PureWindowsPath

import pytest

from harness import job_release

OLD = PureWindowsPath(r"C:\Users\runneradmin\AppData\Local\lh-home\releases\19-aaaaaaaaaaaa")
NEW = PureWindowsPath(r"C:\Users\runneradmin\AppData\Local\lh-home\releases\20-bbbbbbbbbbbb")


@pytest.fixture()
def win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture()
def posix(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


def test_either_separator_after_the_old_release_maps_to_the_new(win32):
    got = job_release.moved([f"{OLD}/.venv/bin/python", "-m", "x", f"{OLD}\\a\\b", str(OLD)], OLD, NEW)
    assert got == [f"{NEW}/.venv/bin/python", "-m", "x", f"{NEW}\\a\\b", str(NEW)]


def test_drive_letter_case_and_forward_slashes_in_the_release_itself_still_match(win32):
    lower = str(OLD).replace("C:", "c:").replace("Users", "USERS")
    slashed = str(OLD).replace("\\", "/")
    got = job_release.moved([f"{lower}\\.venv\\Scripts\\python.exe", f"{slashed}/evals"], OLD, NEW)
    assert got == [f"{NEW}\\.venv\\Scripts\\python.exe", f"{NEW}/evals"]


def test_a_sibling_whose_name_starts_with_the_release_or_a_path_elsewhere_is_left_alone(win32):
    words = [f"{OLD}x\\y", f"{OLD}-old", r"D:\elsewhere", "/elsewhere", "-m"]
    assert job_release.moved(words, OLD, NEW) == words


def test_off_windows_a_backslash_or_another_case_is_part_of_a_file_name(posix):
    old, new = "/home/u/lh/releases/19-aaaaaaaaaaaa", "/home/u/lh/releases/20-bbbbbbbbbbbb"
    words = [f"{old}\\x", old.upper() + "/x", f"{old}x/y"]
    assert job_release.moved(words, old, new) == words
    assert job_release.moved([f"{old}/a/b", old], old, new) == [f"{new}/a/b", new]


def test_the_new_release_names_a_missing_file_given_with_forward_slashes(win32):
    assert "not in release" in job_release.refusal([f"{NEW}/scripts/gone.sh"], NEW)
    assert "not in release" in job_release.refusal([f"{str(NEW).lower()}\\scripts\\gone.sh"], NEW)
    assert job_release.refusal([f"{NEW}x/scripts/gone.sh"], NEW) == ""
