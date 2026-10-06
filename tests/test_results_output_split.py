"""results.output is the text a runner returned; results.artifact_path is the file. #463."""
import argparse
import json
import sqlite3
from pathlib import Path

import pytest

from evals import run as er
from evals.core import Case, Result
from evals.runners import base
from evals.runners.base import BaseRunner
from harness import memory_store as ms, paths, runs

SVG = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
CANONICAL = '{"answers": {"label": "yes"}}'


class _Text(BaseRunner):
    candidate = "org/text"

    def generate(self, case):
        return SVG, 1


class _File(BaseRunner):
    """A process engine that writes the canonical decide artifact itself."""
    candidate = "nimble/x"

    def __init__(self, outdir):
        self.outdir = Path(outdir)

    def generate(self, case):
        out = self.outdir / self.artifact(case, ".json")
        out.write_text(CANONICAL, encoding="utf-8")
        return out, 1


def _execute(monkeypatch, tmp_path, lane, make):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(er, "load_cases",
                        lambda path: [Case(id="a", modality=lane, prompt="p")])
    monkeypatch.setattr(er, "build_runner", lambda *a, **k: make(out))
    monkeypatch.setattr(er, "warn_if_pressed",
                        lambda: argparse.Namespace(as_dict=lambda: {}))
    monkeypatch.setattr(er, "capture", lambda: {"hw_model": "Test,1",
                                                "os": "t", "arch": "a"})
    monkeypatch.setattr(base, "score", lambda case, art, **k: Result(
        case.id, "", True, 0.0, 0, ""))
    args = argparse.Namespace(
        modality=lane, candidates="fake:spec", cases="x", out=str(out),
        screen=False, repeat=1, adherence="", gateway="http://gw",
        from_winners=False)
    assert er._execute(args) == 0
    c = ms.connect()
    try:
        row = runs.rows(c, runs.at(c, out)["id"])[0]
    finally:
        c.close()
    return out, row, json.loads((out / "results.json").read_text(encoding="utf-8"))["rows"][0]


def test_a_text_lane_stores_its_output_and_the_file_it_wrote(monkeypatch, tmp_path):
    out, row, exported = _execute(monkeypatch, tmp_path, "svg", lambda o: _Text())
    assert row["output"] == SVG
    assert Path(row["artifact_path"]) == (out / "org_text--a.svg").resolve()
    assert Path(row["artifact_path"]).read_text(encoding="utf-8") == SVG
    assert exported["output"] == SVG and exported["artifact_path"] == row["artifact_path"]
    assert exported["artifact"] == SVG, "the deprecated key keeps its old meaning"


def test_a_runner_that_wrote_a_file_keeps_it_and_stores_no_output(monkeypatch, tmp_path):
    """The decide engine's own JSON is the artifact; it is not overwritten by its path."""
    out, row, exported = _execute(monkeypatch, tmp_path, "decide", _File)
    f = out / "nimble_x--a.json"
    assert row["output"] is None and row["artifact_path"] == str(f)
    assert f.read_text(encoding="utf-8") == CANONICAL
    assert exported["artifact"] == str(f)


def test_a_media_runner_that_wrote_nothing_has_no_artifact_path(tmp_path):
    class Gone(BaseRunner):
        candidate = "x"

        def generate(self, case):
            return tmp_path / "never-written.png", 1

    r = Gone().run(Case(id="a", modality="image", prompt="p"))
    assert r.output is None and r.artifact_path is None


# --- a receipt from before #463 carries only `artifact` --------------------

def _legacy(lane, rows):
    return {"generated": "2026-10-05T12:00:00", "environment": ms.this_machine(),
            "receipt": {"modality": lane}, "rows": rows}


def _row(cand, value):
    return {"case_id": "a#1", "candidate": cand, "passed": True, "artifact": value}


def test_a_legacy_text_row_is_output_and_its_file_is_found_by_name():
    d = paths.runs() / "r-svg"
    d.mkdir(parents=True)
    (d / "org_a--a#1.svg").write_text(SVG, encoding="utf-8")
    c = ms.connect()
    try:
        rid = runs.record(c, d, _legacy("svg", [_row("org/a", SVG), _row("b", SVG)]))
        got = runs.rows(c, rid)
    finally:
        c.close()
    assert [r["output"] for r in got] == [SVG, SVG]
    assert got[0]["artifact_path"] == str(d / "org_a--a#1.svg")
    assert got[1]["artifact_path"] is None


def test_a_legacy_media_row_is_a_path_even_when_the_file_is_gone():
    c = ms.connect()
    try:
        rid = runs.record(c, paths.runs() / "r-img",
                          _legacy("image", [_row("m", "/gone/m--a#1.png")]))
        got = runs.rows(c, rid)[0]
    finally:
        c.close()
    assert got["output"] is None and got["artifact_path"] == "/gone/m--a#1.png"


@pytest.mark.parametrize("value,lane,kind", [
    ("yes", "extract", "text"),
    ("line one\nline two", "image", "text"),
    ("/elsewhere/n--a#1.json", "decide", "path"),
    ("/elsewhere/other.json", "decide", "text"),
    (None, "svg", "none"),
    ("", "svg", "none"),
])
def test_split_legacy_classifies(value, lane, kind):
    assert runs.split_legacy(value, lane, None, "n", "a#1")[2] == kind


# --- the migration ----------------------------------------------------------

OLD_RUNS_RESULTS = """
    CREATE TABLE runs (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
        lane TEXT NOT NULL DEFAULT '', tier TEXT NOT NULL DEFAULT 'measure',
        machine_id INTEGER, generated_at REAL,
        repeat_count INTEGER NOT NULL DEFAULT 1,
        cases_digest TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '{}',
        environment TEXT NOT NULL DEFAULT '{}', specs TEXT NOT NULL DEFAULT '{}',
        recorded_at REAL NOT NULL, job_id INTEGER);
    CREATE TABLE results (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
        seq INTEGER NOT NULL, candidate_id INTEGER, candidate TEXT NOT NULL,
        case_id TEXT NOT NULL, repeat_index INTEGER NOT NULL DEFAULT 1,
        passed INTEGER NOT NULL, seconds REAL NOT NULL DEFAULT 0,
        peak_kb INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '',
        metrics TEXT NOT NULL DEFAULT '{}', warnings TEXT NOT NULL DEFAULT '[]',
        artifact TEXT,
        failure_class TEXT NOT NULL DEFAULT '',
        hit_limit TEXT NOT NULL DEFAULT '');
"""


def test_the_migration_splits_artifact_into_output_and_artifact_path(old_store, tmp_path):
    img = tmp_path / "m--a#1.png"
    img.write_bytes(b"png")
    d = paths.runs() / "r1"
    d.mkdir(parents=True)
    (d / "org_a--a#1.svg").write_text(SVG, encoding="utf-8")
    rows = f"""
        INSERT INTO runs (id, path, lane, recorded_at) VALUES (1, 'r1', 'svg', 0),
            (2, 'r2', 'image', 0);
        INSERT INTO results (run_id, seq, candidate, case_id, passed, artifact) VALUES
            (1, 0, 'org/a', 'a#1', 1, '{SVG}'),
            (1, 1, 'b', 'a#1', 1, '{SVG}'),
            (1, 2, 'c', 'a#1', 0, NULL),
            (2, 0, 'm', 'a#1', 1, '{img}');
    """
    path = old_store(40, rows, ddl=OLD_RUNS_RESULTS)
    c = ms.connect(path)
    try:
        got = [dict(r) for r in c.execute(
            "SELECT candidate, output, artifact_path FROM results ORDER BY id")]
        counts = json.loads(c.execute(
            "SELECT value FROM meta WHERE key = 'artifact_split'").fetchone()["value"])
        cols = ms._columns(c, "results")
    finally:
        c.close()
    assert got == [
        {"candidate": "org/a", "output": SVG, "artifact_path": str(d / "org_a--a#1.svg")},
        {"candidate": "b", "output": SVG, "artifact_path": None},
        {"candidate": "c", "output": None, "artifact_path": None},
        {"candidate": "m", "output": None, "artifact_path": str(img)}]
    assert counts == {
        "svg": {"path": 0, "text": 2, "none": 1, "resolved": 1, "missing": 1},
        "image": {"path": 1, "text": 0, "none": 0, "resolved": 0, "missing": 0}}
    assert {"output", "artifact_path"} <= cols
    if sqlite3.sqlite_version_info >= (3, 35, 0):
        assert "artifact" not in cols
