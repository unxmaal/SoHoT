"""The incumbent's stored draws stand in for a fresh run when its content identity matches. #1094."""
import json
import os
import time
from pathlib import Path

import pytest

from evals import run as R
from evals import watch
from harness import completion, identity, looks, power, reuse, reverify, runs, watchdog
from harness import memory_store as ms
from harness.commands import measure
from tests.test_interleave_816 import Named
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401

INC, CH = "org/inc", "org/ch"
MACHINE = ({"hw_model": "Mac17,15", "os_build": "26A434", "arch": "arm64", "memory_gb": 96,
            "power": {"lowpowermode": "0"}},
           {"swap_used_mb": 100, "available_gb": 40.0, "thermal": ""})
HARNESS = {"git_sha": "a" * 40, "git_dirty": False, "diff": ""}


@pytest.fixture
def served(tmp_path, monkeypatch):
    """A llama-server binary, a library beside it and a GGUF, all small files whose bytes the tests change."""
    root = tmp_path / "srv"
    (root / "bin").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "gguf").mkdir()
    files = {"binary": root / "bin" / "llama-server", "lib": root / "lib" / "libllama.0.dylib",
             "model": root / "gguf" / "Stem.gguf"}
    for name, f in files.items():
        f.write_bytes(f"{name} v1".encode())
    monkeypatch.setenv("LLAMACPP_BIN", str(files["binary"]))
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(root / "gguf"))
    monkeypatch.setattr(identity, "_linked", lambda exe: [])
    return files


def _rewrite(path: Path, text: str) -> None:
    path.write_bytes(text.encode())
    later = time.time() + 5
    os.utime(path, (later, later))


def _of(spec="llamacpp:Stem", cases=None, machine=MACHINE, harness=HARNESS, **kw):
    lane = kw.pop("lane", "code")
    return identity.of(lane, spec, budget=kw.pop("budget", 32768), cases=cases or [],
                       machine=machine, harness=harness, **kw)


def test_the_served_bytes_are_read_for_a_llama_server_spec(served):
    got = _of()
    assert got["digest"] and not got["unresolved"]
    assert set(got["parts"]["served"]["runtime"]) == {"llama-server", "libllama.0.dylib"}
    assert set(got["parts"]["served"]["model"]) == {"Stem.gguf"}


def _preset(text: str) -> None:
    identity.preset_path().write_text(text, encoding="utf-8")


CHANGES = {
    "binary": lambda f, mp: _rewrite(f["binary"], "binary v2"),
    "library": lambda f, mp: _rewrite(f["lib"], "lib v2"),
    "model file": lambda f, mp: _rewrite(f["model"], "model v2"),
    "preset section": lambda f, mp: _preset("version = 1\n[Stem]\nc = 65536\n"),
    "sampling": lambda f, mp: mp.setitem(completion.SAMPLING, "code", {"temperature": 0.9}),
    "split version": lambda f, mp: mp.setattr("harness.holdout.version", lambda lane: "2"),
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_the_digest_moves_when_any_served_or_sent_input_changes(served, monkeypatch, change):
    _preset("version = 1\n[Stem]\nc = 32768\n")
    before = _of()["digest"]
    CHANGES[change](served, monkeypatch)
    assert _of()["digest"] != before


def test_the_digest_moves_with_the_reply_budget_knobs_cases_harness_and_machine(served):
    from harness.holdout import Split  # noqa: F401
    from evals.core import Case
    case = Case(id="c1", modality="code", prompt="p")
    base = _of(cases=[case])["digest"]
    moved = {
        "budget": _of(cases=[case], budget=16000),
        "spec option": _of("llamacpp:Stem,temperature=0.7", cases=[case]),
        "knob": _of(cases=[case], overrides={"request_timeout": 30.0}),
        "cases": _of(cases=[Case(id="c1", modality="code", prompt="q")]),
        "git sha": _of(cases=[case], harness={**HARNESS, "git_sha": "b" * 40}),
        "dirty diff": _of(cases=[case], harness={**HARNESS, "git_dirty": True, "diff": "d1"}),
        "hw_model": _of(cases=[case], machine=({**MACHINE[0], "hw_model": "Mac14,12"}, MACHINE[1])),
        "os build": _of(cases=[case], machine=({**MACHINE[0], "os_build": "26B1"}, MACHINE[1])),
        "memory": _of(cases=[case], machine=({**MACHINE[0], "memory_gb": 32}, MACHINE[1])),
        "power mode": _of(cases=[case], machine=({**MACHINE[0], "power": {"lowpowermode": "1"}}, MACHINE[1])),
    }
    assert {k for k, v in moved.items() if v["digest"] == base} == set()


def test_the_digest_holds_when_only_swap_or_free_memory_or_thermal_change(served):
    base = _of()
    later = _of(machine=(MACHINE[0], {"swap_used_mb": 20000, "available_gb": 3.5, "thermal": "warm"}))
    assert later["digest"] == base["digest"]
    assert later["timing"]["swap_used_mb"] == 20000


def test_a_spec_whose_model_file_is_missing_has_no_digest(served):
    served["model"].unlink()
    got = _of()
    assert got["digest"] == "" and any(u.startswith("model:") for u in got["unresolved"])


def test_a_file_is_hashed_once_until_its_size_or_mtime_moves(tmp_path, monkeypatch):
    f, cache = tmp_path / "w.gguf", tmp_path / "cache.json"
    f.write_bytes(b"abc")
    calls = []
    real = identity._sha256
    monkeypatch.setattr(identity, "_sha256", lambda p: calls.append(p) or real(p))
    first = identity.file_digest(f, cache)
    assert identity.file_digest(f, cache) == first and len(calls) == 1
    _rewrite(f, "abd")
    assert identity.file_digest(f, cache) != first and len(calls) == 2
    assert len(json.loads(cache.read_text(encoding="utf-8"))) == 1


# --- a paired run ---------------------------------------------------------------------------

@pytest.fixture
def pair(monkeypatch, served, clock):
    """Fake runners for INC and CH whose identity is the fake server's bytes, so changing a file changes it."""
    log = []
    runners = {}

    def build(candidate, *a, **k):
        runners[candidate] = Named(candidate, clock, log)
        return runners[candidate]
    monkeypatch.setattr(R, "build_runner", build)
    monkeypatch.setattr(R, "pair_block", lambda candidates, gateway: 1)
    monkeypatch.setattr(identity, "machine_state", lambda: MACHINE)
    monkeypatch.setattr(identity, "harness_state", lambda root=None: HARNESS)
    monkeypatch.setattr(identity, "served", lambda spec: {
        "engine": "llama-server", "runtime": identity.files_digest([served["binary"], served["lib"]]),
        "model": identity.files_digest([served["model"]]), "preset": {}})
    return runners


def _incumbent_only(tmp_path, name="earlier"):
    out = tmp_path / name
    assert R._execute(_args(out, candidates=INC)) == 0
    return out


def _planned(lane="code"):
    cases = R.load_selected(R.parse_args(["--modality", lane]))
    from harness import holdout
    cells = [c.id for c in R.expand_cases(holdout.only(cases, "holdout"), 1)]
    ident = R.content_identity(lane, INC, R.run_budget(lane, None), (), {}, cases)
    conn = ms.connect()
    try:
        return reuse.plan(conn, lane, ident["digest"], cells), cells
    finally:
        conn.close()


def test_stored_draws_under_the_same_digest_send_no_incumbent_calls(tmp_path, quiet, pair):
    _incumbent_only(tmp_path)
    got, cells = _planned()
    assert got["reused"] == len(cells) and got["fresh"] == 0
    out = tmp_path / "paired"
    reuse.write(out, INC, got)
    assert R._execute(_args(out, candidates=f"{INC},{CH}", reuse=str(out / reuse.REUSE_FILE))) == 0
    assert pair[INC].ran == []
    assert sorted(pair[CH].ran) == sorted(cells)
    head, _ = watch.read(out)
    assert sorted(head["reuse"]["cells"]) == sorted(cells)
    conn = ms.connect()
    try:
        env = json.loads(runs.at(conn, out)["environment"])
    finally:
        conn.close()
    assert env["reused"][INC]["reused"] == len(cells) and env["reused"][INC]["fresh"] == 0
    assert env["identities"][INC]["digest"] == got["digest"]


def test_a_case_without_a_matching_draw_runs_fresh(tmp_path, quiet, pair):
    _incumbent_only(tmp_path)
    conn = ms.connect()
    try:
        run_id = runs.at(conn, tmp_path / "earlier")["id"]
        first = conn.execute("SELECT case_id FROM results WHERE run_id = ? ORDER BY seq LIMIT 1",
                             (run_id,)).fetchone()[0]
        conn.execute("DELETE FROM results WHERE run_id = ? AND case_id = ?", (run_id, first))
        conn.commit()
    finally:
        conn.close()
    got, cells = _planned()
    out = tmp_path / "paired"
    reuse.write(out, INC, got)
    R._execute(_args(out, candidates=f"{INC},{CH}", reuse=str(out / reuse.REUSE_FILE)))
    assert pair[INC].ran == [first] and got["fresh"] == 1


@pytest.mark.parametrize("change", ["binary", "model file", "sampling"])
def test_the_same_rows_under_a_changed_binary_model_or_sampling_run_fresh(tmp_path, quiet, pair, served,
                                                                          monkeypatch, change):
    _incumbent_only(tmp_path)
    stale, cells = _planned()
    CHANGES[change](served, monkeypatch)
    got, _ = _planned()
    assert got["reused"] == 0 and got["fresh"] == len(cells)
    # A plan written before the change is refused by the run itself.
    out = tmp_path / "paired"
    reuse.write(out, INC, stale)
    R._execute(_args(out, candidates=f"{INC},{CH}", reuse=str(out / reuse.REUSE_FILE)))
    assert sorted(pair[INC].ran) == sorted(cells)
    assert "reuse" not in watch.read(out)[0]


def test_the_measure_step_pairs_the_stored_cells_with_the_challenger(tmp_path, quiet, pair):
    _incumbent_only(tmp_path)
    got, cells = _planned()
    out = tmp_path / "paired"
    reuse.write(out, INC, got)
    R._execute(_args(out, candidates=f"{INC},{CH}", reuse=str(out / reuse.REUSE_FILE),
                     stop_at=watch.clock() + 10.0 * 20 - 1))
    _, rows = watch.read(out)
    plan = measure._resumed_plan({"repeat": 1, "power": 0.5, "cells": len(cells), "cases": len(cells),
                                  "effect": 0.2, "alpha": 0.05, "target": 0.8, "cap": 16, "capped": False,
                                  "stochastic": True, "observed": 0, "why": "", "side": "holdout",
                                  "odds": [0.2, 0.05], "reuse": got},
                                 power.Plan(1, 0.5, 1, 1, 0.2, 0.05, 0.8, 16, False, True, 0, ""))
    conn = ms.connect()
    try:
        merged, _, evidence = measure._merge_reused(conn, out, plan, rows, {}, INC)
    finally:
        conn.close()
    assert evidence["reused"] == len(cells)
    from harness import holdout
    look, _ = looks.look(merged, lane="code", inc_key=INC, ch_key=CH, split=holdout.for_lane("code"),
                         plan=plan.as_dict(), alpha=0.05, spent_before=0.0, n=1)
    assert look.text.startswith(f"look 1 at {len(rows)}/{len(cells)} holdout cells")


def test_a_checkpoint_from_before_identities_were_recorded_still_resumes():
    had = {"modality": "code", "repeat": 1}
    assert watch.differs(had, {**had, "identities": {INC: "d1"}}) == []
    assert watch.differs({**had, "identities": {INC: "d1"}}, {**had, "identities": {INC: "d2"}}) == ["identities"]


def test_the_watchdog_judges_the_challenger_against_the_stored_incumbent_time(tmp_path, quiet, pair):
    _incumbent_only(tmp_path)
    got, cells = _planned()
    out = tmp_path / "paired"
    reuse.write(out, INC, got)
    R._execute(_args(out, candidates=f"{INC},{CH}", reuse=str(out / reuse.REUSE_FILE),
                     stop_at=watch.clock() + 10.0 * 6 - 1))
    _, by = watchdog._cells({"_dir": str(out), "specs": {INC: INC, CH: CH}})
    assert len(by[INC]) == len(cells)
    assert watchdog._paired(by, INC, CH) is not None


def test_reverify_names_a_model_whose_bytes_moved(served):
    ident = _of()
    run = {"environment": json.dumps({"identities": {"llamacpp:Stem": ident}})}
    assert reverify.bytes_moved(run, "llamacpp:Stem") == []
    _rewrite(served["model"], "model v2")
    assert reverify.bytes_moved(run, "llamacpp:Stem") == ["model bytes changed: Stem.gguf"]


# --- the known-answer replay ------------------------------------------------------------------

def _stored(conn, path, rows, when, max_tokens=32768, specs=None):
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(when)),
            "receipt": {"modality": "code", "tier": "measure", "max_tokens": max_tokens, "split": "holdout",
                        "split_version": "1", "sampling": {"code": {"temperature": 0.2}}, "knobs": {}},
            "environment": {"hw_model": "Mac17,15", "macos": "27.0.1", "memory_gb": 96,
                            "versions": {"llama.cpp": "11146"}},
            "specs": specs or {INC: INC}, "rows": rows}
    return runs.record(conn, path, data, at=when)


def row(who, case, ok):
    return {"candidate": who, "case_id": case, "passed": ok, "seconds": 1.0}


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/reuse.py:replay")
def test_the_replay_takes_draws_only_from_earlier_runs_that_match_and_reads_the_newest_pause(tmp_path):
    from harness import holdout
    held = list(holdout.for_lane("code").holdout)[:10]
    conn = ms.connect()
    try:
        source = _stored(conn, tmp_path / "src", [row(INC, c, True) for c in held], 1_000.0)
        _stored(conn, tmp_path / "other", [row(INC, c, False) for c in held], 1_100.0, max_tokens=16000)
        _stored(conn, tmp_path / "after", [row(INC, c, False) for c in held], 9_000.0)
        target = _stored(conn, tmp_path / "target",
                         [r for c in held for r in (row(INC, c, False), row(CH, c, True))], 2_000.0,
                         specs={INC: INC, CH: CH})
        plan = {"repeat": 1, "alpha": 0.05, "odds": [0.2, 0.05], "cells": len(held), "cases": len(held)}
        for looks_, why in (([], "look 1 at 3/10 holdout cells: stale"),
                            ([{"text": "look 1 at 4/10 holdout cells: continues"}], "look 2 at 8/10 holdout cells")):
            conn.execute("INSERT INTO paused_runs (lane, incumbent, challenger, out, plan, looks, state, why, "
                         "run_id, paused_at) VALUES ('code', ?, ?, ?, ?, ?, 'done', ?, ?, 0)",
                         (INC, CH, str(tmp_path / "target"), json.dumps(plan), json.dumps(looks_), why, target))
        conn.commit()
        got = reuse.replay(conn, target)
    finally:
        conn.close()
    assert got["matching_runs"] == [source]
    assert got["reused"] == len(held) and got["runs"] == {str(source): len(held)}
    assert got["control"]["looks"][0].startswith("look 1 at 4/") and len(got["control"]["looks"]) == 2
    # The incumbent failed every case in the run and passed every one in the matching earlier run.
    assert "4 gained" in got["control"]["looks"][0] and "0 gained, 0 lost" in got["replay"]["looks"][0]
