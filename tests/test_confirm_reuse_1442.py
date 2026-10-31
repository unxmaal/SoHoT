"""A confirmation takes the incumbent's dev cells stored draws cover, as the measure step does. #1442, #1094."""
import json
import time
import types
from pathlib import Path

import pytest

from evals import watch
from harness import paths, reuse, runs
from harness.commands import measure as measure_cmd
from tests.test_confirm_resume_1357 import CELLS, _held, _rows, conn  # noqa: F401

STORED = [f"d{i}" for i in range(5)]


def _store_incumbent(conn):
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "specs": {"inc-key": "inc-spec"},
            "receipt": {"modality": "code", "tier": "measure", "split": "dev"}, "environment": {},
            "rows": [{"candidate": "inc-key", "case_id": c, "passed": False, "seconds": 1.0} for c in STORED]}
    return runs.record(conn, "earlier-confirm-code", data, at=time.time() - 3600)


def _planned(run_id):
    return {"digest": "d" * 64, "min_draws": 1, "runs": {str(run_id): len(STORED)}, "reused": len(STORED),
            "fresh": len(CELLS) - len(STORED), "cells": {c: [run_id, c, "inc-key", 1.0, None, "x"] for c in STORED}}


def _fake_eval(monkeypatch, seen):
    """evals.run as a confirmation sees it, skipping the incumbent cells its --reuse file names."""
    def launch(argv, **kw):
        seen.append(argv)
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        got = reuse.read(argv[argv.index("--reuse") + 1]) if "--reuse" in argv else {}
        skip = sorted(got.get("cells") or ())
        ident = {"modality": "code", "candidates": argv[argv.index("--candidates") + 1].split(","), "repeat": 1,
                 "split": "dev", **({"reuse": {"digest": got["digest"], "cells": skip}} if skip else {})}
        ckpt = watch.Checkpoint(out, ident)
        for row in _rows(CELLS, "inc-key", "ch-key"):
            if not (row["candidate"] == "inc-key" and row["case_id"] in skip):
                ckpt.add(row, 1.0)
        (out / watch.PROGRESS).write_text(json.dumps({"state": "done"}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(measure_cmd, "_launch", launch)
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {
        "specs": {"inc-key": "inc-spec", "ch-key": "org/x"}, "rows": watch.read(out)[1]})


def _verdict(conn):
    return conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()


def test_a_confirmation_skips_the_stored_incumbent_cells_and_pairs_them(conn, tmp_path, monkeypatch, capsys):
    vid = _held(conn, tmp_path, monkeypatch)
    run_id = _store_incumbent(conn)
    asked = []
    monkeypatch.setattr(measure_cmd, "_stored_cells", lambda lane, inc, ch, side, repeat: (
        asked.append((lane, inc, ch, side, repeat)) or _planned(run_id)))
    seen = []
    _fake_eval(monkeypatch, seen)
    assert measure_cmd.confirm_job(vid) == 0
    assert asked == [("code", "inc-spec", "org/x", "dev", 1)]
    assert "--reuse" in seen[0]
    got = _verdict(conn)
    assert "confirmed on 10 dev case(s): 9 gained against 0 lost" in got["detail"], got["detail"]
    assert f"incumbent: {len(STORED)} cell(s) reused from run {run_id}" in capsys.readouterr().out


def test_no_stored_draws_leaves_the_argv_as_it_was(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    monkeypatch.setattr(measure_cmd, "_stored_cells", lambda *a: {
        "digest": "d" * 64, "cells": {}, "runs": {}, "reused": 0, "fresh": len(CELLS)})
    seen = []
    _fake_eval(monkeypatch, seen)
    assert measure_cmd.confirm_job(vid) == 0
    assert "--reuse" not in seen[0]
    assert "confirmed on 10 dev case(s)" in _verdict(conn)["detail"]


def test_a_resumed_confirmation_keeps_the_reuse_file_it_started_with(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    out = paths.home() / "runs" / "20261005-000000-confirm-code"
    out.mkdir(parents=True)
    watch.Checkpoint(out, {"modality": "code", "candidates": ["inc-spec", "org/x"], "repeat": 1, "split": "dev"})
    (out / watch.PROGRESS).write_text(json.dumps({"state": "paused"}), encoding="utf-8")
    kept = reuse.write(out, "inc-spec", _planned(_store_incumbent(conn)))
    monkeypatch.setattr(measure_cmd, "_stored_cells", lambda *a: pytest.fail("a resume planned reuse again"))
    seen = []
    _fake_eval(monkeypatch, seen)
    assert measure_cmd.confirm_job(vid) == 0
    assert "--resume" in seen[0] and seen[0][seen[0].index("--reuse") + 1] == str(kept)
