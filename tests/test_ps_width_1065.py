"""#1065: a process's command line is read in full, whatever the screen width, so a long argv still matches."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from harness import sweep_guard, watchdog

REPO = Path(__file__).resolve().parents[1]
SOURCES = ("harness", "evals", "scripts", "gateway", "tools", "voice", "deploy")
PY_PS = re.compile(r"\[\s*[\"']ps[\"']\s*,[^\]]*\]")
SH_PS = re.compile(r"(?:^|[\s;|&(`])ps\s+-[^\n;|)]*", re.M)
COMMAND_FIELD = re.compile(r"\b(?:command|args|cmd)\b")


def _ps_calls():
    for d in SOURCES:
        for f in sorted((REPO / d).rglob("*")) if (REPO / d).is_dir() else []:
            if f.suffix not in (".py", ".sh") or "cases" in f.relative_to(REPO).parts:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            for m in (PY_PS if f.suffix == ".py" else SH_PS).finditer(text):
                yield f"{f.relative_to(REPO)}:{text.count(chr(10), 0, m.start()) + 1}", m.group(0)


def test_every_ps_that_reads_a_command_line_asks_for_unlimited_width():
    reading = {where: call for where, call in _ps_calls() if COMMAND_FIELD.search(call)}
    assert {w.split(":")[0] for w in reading} >= {"harness/sweep_guard.py", "harness/watchdog.py"}
    assert [f"{w}: {c}" for w, c in reading.items() if "-ww" not in c] == []


@pytest.fixture
def long_argv():
    """A child whose argv runs past 200 characters and ends in a marker a cut-off read would lose."""
    tail = "discover --loop"
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "x" * 200, *tail.split()])
    yield proc.pid, tail
    proc.kill()
    proc.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="ps is POSIX")
def test_command_of_keeps_the_tail_of_a_long_argv_at_80_columns(long_argv, monkeypatch):
    pid, tail = long_argv
    monkeypatch.setenv("COLUMNS", "80")
    got = sweep_guard.command_of(pid)
    assert got and got.endswith(tail), got
    assert sweep_guard.LOOP.search(got)


@pytest.mark.skipif(sys.platform == "win32", reason="ps is POSIX")
def test_the_watchdog_listing_keeps_the_tail_of_a_long_argv_at_80_columns(long_argv, monkeypatch):
    pid, tail = long_argv
    monkeypatch.setenv("COLUMNS", "80")
    got = {p.pid: p.command for p in watchdog.Probes().processes() or []}
    assert got.get(pid, "").endswith(tail), got.get(pid)
