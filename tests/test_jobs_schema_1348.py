"""A job whose checkout speaks an older schema than the store fails at queue time, not at its night start. #1348."""
import pytest

from harness import memory_store as ms
from harness import workqueue as wq


def checkout(tmp_path, version, name="wt"):
    top = tmp_path / name
    (top / "harness" / "memory_store").mkdir(parents=True)
    (top / "harness" / "memory_store" / "schema.py").write_text(
        f'"""The store\'s shape."""\n\nSCHEMA_VERSION = {version}\n', encoding="utf-8")
    (top / "evals").mkdir()
    return top


def test_the_code_schema_is_read_from_the_nearest_checkout(tmp_path):
    top = checkout(tmp_path, 83)
    assert wq.code_schema(top) == 83 and wq.code_schema(top / "evals") == 83
    assert wq.code_schema(tmp_path) is None


def test_a_stale_checkout_is_refused_at_add_naming_both_versions(tmp_path):
    top = checkout(tmp_path, ms.SCHEMA_VERSION - 2)
    with pytest.raises(ValueError) as got:
        wq.add(["true"], cwd=str(top / "evals"))
    text = str(got.value)
    assert f"schema {ms.SCHEMA_VERSION - 2}" in text and f"schema {ms.SCHEMA_VERSION}" in text
    assert str(top) in text and wq.pending() == []


@pytest.mark.parametrize("ahead", [0, 1])
def test_a_current_or_newer_checkout_and_a_plain_directory_queue(tmp_path, ahead):
    top = checkout(tmp_path, ms.SCHEMA_VERSION + ahead)
    assert wq.add(["true"], cwd=str(top))["state"] == wq.PENDING
    assert wq.add(["true"], cwd=str(tmp_path))["state"] == wq.PENDING


def test_a_job_gone_stale_since_its_add_fails_at_start_without_running(tmp_path):
    top = checkout(tmp_path, ms.SCHEMA_VERSION)
    job = wq.add(["true"], cwd=str(top))
    (top / "harness" / "memory_store" / "schema.py").write_text(
        f"SCHEMA_VERSION = {ms.SCHEMA_VERSION - 2}\n", encoding="utf-8")
    ran = []
    got = wq.run_one(job, popen=lambda *a, **k: ran.append(a))
    assert ran == [] and got["state"] == wq.FAILED
    assert f"schema {ms.SCHEMA_VERSION - 2}" in got["note"]
    assert f"schema {ms.SCHEMA_VERSION - 2}" in open(got["log"], encoding="utf-8").read()
