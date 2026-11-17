"""check-postgres splits a large selection across runners by recorded seconds; a small one stays on one (#2060)."""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests import shells
from tests.gauntlet import scope, shard

CI = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
FILES = [f"tests/test_{i:03d}.py" for i in range(700)]


def test_a_small_selection_runs_on_one_runner_and_a_large_one_on_at_most_max():
    assert shard.count(FILES[:shard.FILES_PER_SHARD]) == 1
    assert shard.count(FILES[:shard.FILES_PER_SHARD + 1]) == 2
    assert shard.count(FILES * 3) == shard.MAX_SHARDS
    assert shard.count([]) == 1


def test_every_file_lands_in_exactly_one_shard_and_the_split_is_the_same_each_time():
    secs = {f: float(i % 17 + 1) for i, f in enumerate(FILES)}
    parts = shard.split(FILES, 3, secs)
    assert sorted(f for p in parts for f in p) == sorted(FILES)
    assert parts == shard.split(list(reversed(FILES)), 3, dict(reversed(list(secs.items()))))


def test_the_shards_are_balanced_by_recorded_seconds_not_by_count():
    heavy = {"tests/test_slow.py": 600.0}
    secs = {**heavy, **{f: 1.0 for f in FILES[:600]}}
    a, b = shard.split([*heavy, *FILES[:600]], 2, secs)
    assert a == ["tests/test_slow.py"] and len(b) == 600


def test_a_file_with_no_recorded_time_weighs_the_median():
    secs = {"tests/test_a.py": 10.0, "tests/test_b.py": 10.0, "tests/test_c.py": 30.0}
    assert shard.weights(["tests/test_a.py", "tests/test_new.py"], secs)["tests/test_new.py"] == 10.0
    assert shard.weights(["tests/test_new.py"], {})["tests/test_new.py"] == 1.0


def test_with_no_listing_the_plan_enumerates_the_whole_suite(tmp_path):
    out = shard.plan(None, None, tracked=["tests/test_a.py", "tests/test_b.py", "harness/x.py", "tests/conftest.py"])
    assert out == {"1": "tests/test_a.py\ntests/test_b.py\n"}


def test_a_dispatch_s_named_tests_run_on_one_leg_whatever_the_selection(tmp_path):
    listing = tmp_path / "selected.txt"
    listing.write_text("".join(f + "\n" for f in FILES), encoding="utf-8")
    assert shard.plan(listing, None, tests="tests/test_a.py::test_x") == {"1": ""}


def test_a_listing_is_split_and_the_plan_is_keyed_by_the_matrix_leg(tmp_path):
    listing = tmp_path / "selected.txt"
    listing.write_text("".join(f + "\n" for f in FILES), encoding="utf-8")
    out = shard.plan(listing, None)
    assert list(out) == [str(i) for i in range(1, shard.count(FILES) + 1)]
    assert sorted(f for v in out.values() for f in v.split()) == FILES


def test_the_listing_scope_wrote_is_what_conftest_reads(tmp_path):
    out = shard.plan(None, None, tracked=["tests/test_a.py", "tests/test_b.py"])
    listing = tmp_path / "leg.txt"
    listing.write_text(out["1"], encoding="utf-8")
    assert not scope.ignored(tmp_path / "tests/test_a.py", tmp_path, listing)
    assert scope.ignored(tmp_path / "tests/test_c.py", tmp_path, listing)


def _ci():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_check_postgres_runs_one_leg_per_planned_shard_and_every_leg_finishes():
    doc = _ci()
    job = doc["jobs"]["check-postgres"]
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["shard"] == "${{ fromJSON(needs.store-touched.outputs.shards || '[1]') }}"
    plan = next(s for s in doc["jobs"]["store-touched"]["steps"] if "tests.gauntlet.shard" in s.get("run", ""))
    assert plan["id"] in doc["jobs"]["store-touched"]["outputs"]["shards"]
    env = next(s for s in job["steps"] if s.get("name") == "This leg's tests")["env"]
    assert "matrix.shard" in env["PLAN"]


@pytest.mark.skipif(shells.BASH is None, reason="needs bash")
def test_the_plan_step_writes_a_leg_list_github_can_expand(tmp_path):
    doc = _ci()
    step = next(s for s in doc["jobs"]["store-touched"]["steps"] if "tests.gauntlet.shard" in s.get("run", ""))
    listing = tmp_path / "selected.txt"
    listing.write_text("".join(f + "\n" for f in FILES), encoding="utf-8")
    out = tmp_path / "out"
    env = {**os.environ, "GITHUB_OUTPUT": str(out), "RUNNER_TEMP": str(tmp_path), "TESTS": ""}
    run = step["run"].replace("uv run --no-project --python 3.12 python", shlex.quote(sys.executable))
    r = subprocess.run([shells.BASH, "-c", run], env=env, capture_output=True, text=True,
                       cwd=CI.parents[2], timeout=60)
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    shards = next(line.split("=", 1)[1] for line in text.splitlines() if line.startswith("shards="))
    plan = json.loads(text.split("plan<<EOF\n", 1)[1].rsplit("\nEOF", 1)[0])
    assert json.loads(shards) == [int(k) for k in plan] == list(range(1, shard.count(FILES) + 1))
