"""A paired run's time projection is priced on this machine and per candidate, and its deadline starts at the lock. #696."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import adopt, completion, power
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from tests.shells import BASH

REPO = Path(__file__).resolve().parents[1]


def _ns(**kw):
    base = {"repeat": 1, "effect": 0.4, "power_budget_min": 10_000_000}
    return argparse.Namespace(**{**base, **kw})


def _rows(lane, spec, seconds, per_case=4):
    from harness import holdout
    split = holdout.for_lane(lane)
    return [{"case_id": f"{c}#{k}", "candidate": spec, "passed": k % 2 == 0,
             "seconds": seconds, "peak_kb": 0, "detail": ""}
            for c in (*split.dev, *split.holdout) for k in range(1, per_case + 1)]


def _budget(lane):
    return {"max_tokens": completion.budget(lane)}


def test_the_incumbent_median_is_this_machines_not_the_one_with_most_rows(store_run):
    store_run("a-1", "code", rows=_rows("code", "inc", 10.0), hw_model="OtherBox1,1", receipt=_budget("code"))
    store_run("a-2", "code", rows=_rows("code", "inc", 10.0), hw_model="OtherBox1,1", receipt=_budget("code"))
    store_run("b-1", "code", rows=_rows("code", "inc", 100.0), receipt=_budget("code"))
    store_run("ch-1", "code", rows=_rows("code", "ch", 100.0), tier="screen", receipt=_budget("code"))
    _, plan = measure_cmd._plan(_ns(), "code", "inc", "ch")
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * 2 * 100.0)


def test_a_challenger_three_times_slower_is_priced_at_its_own_speed_and_the_inputs_are_kept(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", 10.0), receipt=_budget("code"))
    store_run("ch-1", "code", rows=_rows("code", "ch", 30.0), tier="screen", receipt=_budget("code"))
    _, plan = measure_cmd._plan(_ns(), "code", "inc", "ch")
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * (10.0 + 30.0))
    est = plan.as_dict()["estimate"]
    assert est["incumbent_s"] == pytest.approx(10.0) and est["incumbent_source"] == "measured"
    assert est["challenger_s"] == pytest.approx(30.0) and est["challenger_source"] == "measured"


def test_a_challenger_measured_only_elsewhere_is_scaled_by_its_size(store_run):
    from harness import candidates
    store_run("inc-1", "code", rows=_rows("code", "inc", 10.0), receipt=_budget("code"))
    store_run("ch-1", "code", rows=_rows("code", "ch", 1.0), tier="screen", hw_model="OtherBox1,1",
              receipt=_budget("code"))
    conn = ms.connect()
    try:
        for name, size in (("org/inc", 10 * 1024 ** 3), ("org/ch", 40 * 1024 ** 3)):
            ms.record(conn, ms.Seen(name=name, source="t", lane="code"))
            ms.set_size(conn, name, size)
        candidates.ensure(conn, "inc", proposal="org/inc", lane="code")
        candidates.ensure(conn, "ch", proposal="org/ch", lane="code")
        conn.commit()
    finally:
        conn.close()
    _, plan = measure_cmd._plan(_ns(), "code", "inc", "ch")
    assert plan.estimate["challenger_source"] == "size ratio"
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * (10.0 + 40.0))


def test_a_challenger_nothing_is_known_about_is_priced_at_the_slowest_decode(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", 10.0), receipt=_budget("code"))
    _, plan = measure_cmd._plan(_ns(), "code", "inc", "ch")
    floor = completion.budget("code") / completion.MIN_DECODE_TOK_S
    assert plan.estimate["challenger_source"] == "floor"
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * (10.0 + floor))


def test_an_unlisted_machine_estimates_at_the_slowest_decode_not_the_studios():
    assert power.decode_tok_s("SomeOtherBox9,9") == completion.MIN_DECODE_TOK_S
    assert power.decode_tok_s("Mac17,15") == 145.0


def test_the_deadline_rate_and_the_grace_are_registered_knobs():
    from harness import knobs
    sites = knobs.registered()
    assert "harness/power.py:DEADLINE_GRACE" in sites
    assert any(s.startswith("harness/power.py:DECODE_TOK_S") for s in sites)


HOLDER = """
import pathlib, sys, time
from harness import exclusive
with exclusive.held("eval"):
    pathlib.Path(sys.argv[1]).write_text("held", encoding="utf-8")
    time.sleep(float(sys.argv[2]))
"""

CHILD = """
from harness import exclusive
with exclusive.held("eval"):
    print("ran", flush=True)
"""


def test_the_deadline_starts_when_the_lock_is_taken_not_at_launch(tmp_path):
    marker = tmp_path / "held"
    env = {k: v for k, v in os.environ.items() if k != "LH_GPU_LOCK_HELD"}
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(marker), "4"], cwd=str(REPO), env=env)
    try:
        until = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < until:
            time.sleep(0.05)
        assert marker.exists(), "the holder never took the lock"
        got = measure_cmd._launch([sys.executable, "-c", CHILD], deadline_s=2.0, cwd=str(REPO), grace_s=1.0)
    finally:
        holder.wait(timeout=30)
    assert not got.timed_out, "waiting for the lock spent the run's deadline"
    assert got.returncode == 0


def _power_row(tmp_path, capsys, monkeypatch, served):
    from harness import candidates, cli, holdout
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: served)
    key = candidates.key_of(served)
    ids = holdout.for_lane("code").holdout
    rows = [{"case_id": f"{c}#{k}", "candidate": key, "passed": i % 4 != 0, "seconds": 2.0}
            for i, c in enumerate(ids) for k in (1, 2, 3)]
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "code"}, "rows": rows}), encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "code", "--receipt", str(receipt)]) == 0
    return json.loads(capsys.readouterr().out)["lanes"][0]


def test_adopt_power_prices_a_best_of_3_incumbent_at_its_calls(tmp_path, capsys, monkeypatch):
    row = _power_row(tmp_path, capsys, monkeypatch, "best-of:3:llamacpp:Ornith-1.5-35B-Q4_K_M")
    assert row["projected_s"] == pytest.approx(row["cases"] * row["repeat"] * 4 * 2.0)
    assert row["calls"] == 4


def _discover_argv(tmp_path, extra):
    if BASH is None:
        pytest.skip("no usable bash")
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "serve-discover.sh", tmp_path / "scripts" / "serve-discover.sh")
    (tmp_path / "scripts" / "env.sh").write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text('#!/usr/bin/env bash\nfor a in "$@"; do printf \'%s\\n\' "$a"; done\n', encoding="utf-8")
    uv.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "DISCOVER_REPEAT"}
    env.update(PATH=f"{tmp_path / 'bin'}{os.pathsep}{env.get('PATH', '')}",
               LOCALHARNESS_HOME=str(tmp_path / "home"), **extra)
    got = subprocess.run([BASH, str(tmp_path / "scripts" / "serve-discover.sh")], env=env,
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    return got.stdout.splitlines()


def test_the_scheduled_sweep_leaves_repeat_to_the_power_plan(tmp_path):
    assert "--repeat" not in _discover_argv(tmp_path, {})


def test_an_owner_set_repeat_still_reaches_the_loop(tmp_path):
    argv = _discover_argv(tmp_path, {"DISCOVER_REPEAT": "5"})
    assert argv[argv.index("--repeat") + 1] == "5"
