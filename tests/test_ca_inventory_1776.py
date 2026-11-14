"""#1776: each copy follows the input its key used to leave out, and a stale copy is never served."""
import json
import os
import time

import pytest
import yaml

from harness import cli, downloads, github, ledger, machine, paths, reuse, runs, screen, serving, stages
from harness import memory_store as ms
from tests.test_harness_github import runner


def _later(path) -> None:
    """Move a path's mtime a second on, as a real upgrade minutes later would; a coarse clock cannot hide it."""
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


# ---- CA-2: machines.versions follows an upgrade under a running process ----

def test_an_upgrade_under_a_running_process_is_written_back_as_the_new_version(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "llama-server"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("LLAMACPP_BIN", str(exe))
    build = {"now": "11146"}
    monkeypatch.setattr(serving, "llamacpp_build", lambda binary="": build["now"])
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(ms.machines, "_RESOLVED_AT", None)
    conn = ms.connect()
    try:
        mid = ms.remember_machine(conn)
        conn.commit()
        assert ms.machines.recorded_facts(conn, mid)["versions"]["llama.cpp"] == "11146"
        # brew upgrade llama.cpp: a new binary under the same name, and no restart.
        exe.write_text("#!/bin/sh\n# 12024\n", encoding="utf-8")
        _later(exe)
        build["now"] = "12024"
        mid = ms.remember_machine(conn)
        conn.commit()
        assert ms.machines.recorded_facts(conn, mid)["versions"]["llama.cpp"] == "12024"
    finally:
        conn.close()


def test_the_versions_probe_follows_a_venv_upgraded_under_it(tmp_path, monkeypatch):
    site = tmp_path / "hf-task" / "lib" / "python3.12" / "site-packages"
    (site / "transformers-5.17.0.dist-info").mkdir(parents=True)
    monkeypatch.setattr(machine, "_keyed_venvs", lambda: {"hf-task": tmp_path / "hf-task"})
    assert machine.versions()["hf-task/transformers"] == "5.17.0"
    (site / "transformers-5.17.0.dist-info").rename(site / "transformers-5.18.0.dist-info")
    _later(site)
    assert machine.versions()["hf-task/transformers"] == "5.18.0"


# ---- CA-8: the mflux tool venv is read now, not at process start ----

def test_the_tool_venv_is_read_as_it_is_now(tmp_path):
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    (site / "mflux-0.19.1.dist-info").mkdir(parents=True)
    assert stages.tool_versions(tmp_path)["mflux"] == "0.19.1"
    (site / "mflux-0.19.1.dist-info").rename(site / "mflux-0.20.0.dist-info")
    assert stages.tool_versions(tmp_path)["mflux"] == "0.20.0"


# ---- CA-3: a resumed reuse plan re-checks the stored run it takes cells from ----

def _incumbent_run(conn, digest: str, case_digest: str = "x") -> int:
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "specs": {"inc-key": "inc-spec"},
            "receipt": {"modality": "code", "tier": "measure", "split": "dev"},
            "environment": {"identities": {"inc-key": {"digest": digest, "cases": {"c1": case_digest}}}},
            "rows": [{"candidate": "inc-key", "case_id": "c1", "passed": True, "seconds": 1.0}]}
    return runs.record(conn, "earlier-incumbent-code", data, at=time.time() - 3600)


@pytest.mark.parametrize("digest, case_digest", [("e" * 64, "x"), ("d" * 64, "y")])
def test_a_resume_after_the_stored_run_was_restored_under_another_identity_takes_nothing_from_it(
        digest, case_digest):
    conn = ms.connect()
    try:
        _incumbent_run(conn, "d" * 64)
        planned = reuse.plan(conn, "code", "d" * 64, ["c1"], cases={"c1": "x"})
        assert planned["reused"] == 1
        extra, gone = reuse.rows(conn, planned, "inc-key")
        assert [r["case_id"] for r in extra] == ["c1"] and gone == []
        _incumbent_run(conn, digest, case_digest)
        extra, gone = reuse.rows(conn, planned, "inc-key")
        assert extra == [] and gone == ["c1"]
    finally:
        conn.close()


def test_a_plan_written_before_it_named_its_runs_identities_still_merges():
    conn = ms.connect()
    try:
        _incumbent_run(conn, "d" * 64)
        planned = reuse.plan(conn, "code", "d" * 64, ["c1"], cases={"c1": "x"})
        old = {k: v for k, v in planned.items() if k != "stored"}
        _incumbent_run(conn, "e" * 64)
        extra, gone = reuse.rows(conn, json.loads(json.dumps(old)), "inc-key")
        assert [r["case_id"] for r in extra] == ["c1"] and gone == []
    finally:
        conn.close()


# ---- CA-5: a snapshot whose blob is gone is not a download ----

def test_a_snapshot_linking_to_a_missing_blob_cannot_be_opened_offline(tmp_path):
    hub = tmp_path / "models--org--m"
    (hub / "refs").mkdir(parents=True)
    (hub / "refs" / "main").write_text("abc", encoding="utf-8")
    snap, blobs = hub / "snapshots" / "abc", hub / "blobs"
    snap.mkdir(parents=True)
    blobs.mkdir()
    for name, blob in (("config.json", "b1"), ("model-00001-of-00002.safetensors", "b2"),
                       ("model-00002-of-00002.safetensors", "b3")):
        (blobs / blob).write_text("x", encoding="utf-8")
        try:
            (snap / name).symlink_to(blobs / blob)
        except OSError:
            pytest.skip("this filesystem makes no symlinks")
    assert downloads.offline_gap(downloads.HUB, hub) == ""
    (blobs / "b3").unlink()
    gap = downloads.offline_gap(downloads.HUB, hub)
    assert "model-00002-of-00002.safetensors" in gap and "blob" in gap


# ---- CA-7: a long process sees a case added after its first screen ----

def _case(root, cid, **extra):
    d = root / "svg"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.yaml").write_text(yaml.safe_dump(
        {"id": cid, "modality": "svg", "prompt": f"draw {cid}", **extra}), encoding="utf-8")
    _later(d)


def test_a_case_added_while_the_process_runs_is_screened_against(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    _case(root, "a", methods=["llm"])
    monkeypatch.setattr(screen, "CASES", root)
    assert screen.case_gap("svg", "omnisvg:8B") == "no svg case fits the omnisvg method (a takes llm)"
    _case(root, "b")
    assert screen.case_gap("svg", "omnisvg:8B") == ""


# ---- CA-10: a cached answer never outlives a shortened discovery interval ----

def test_a_star_list_cached_longer_than_a_shortened_interval_is_refetched(tmp_path, monkeypatch):
    from harness import feeds
    monkeypatch.setenv(feeds.INTERVAL_ENV, "1")
    r = runner({"users/u/starred?per_page=100&page=1": [{"full_name": "a/b"}]})
    github.Client(cache=tmp_path, runner=r).starred("u")
    cached = next(tmp_path.glob("*.json"))
    payload = json.loads(cached.read_text(encoding="utf-8"))
    payload["fetched"] = time.time() - 30 * 3600
    cached.write_text(json.dumps(payload), encoding="utf-8")
    again = github.Client(cache=tmp_path, runner=r)
    again.starred("u")
    assert again.spent == 1


def test_every_ttl_stays_under_the_interval_it_was_sized_against(monkeypatch):
    from harness import feeds
    for days in (1, 3, feeds.DEFAULT_INTERVAL_DAYS):
        monkeypatch.setenv(feeds.INTERVAL_ENV, str(days))
        assert github.ttl_for("users/x/starred") < days * 24


# ---- CA-9: a ledger day no run rewrote after it ended is recorded again ----

def _day(days_ago: int) -> str:
    return ledger.days_between(time.time() - days_ago * 86400, time.time())[0]


def _ledger_rows(rows: dict) -> None:
    conn = ms.connect()
    for day, at in rows.items():
        conn.execute("INSERT INTO ledger_days (day, recorded_at, energy_kwh, detail) VALUES (?, ?, NULL, '{}')", (day, at))
    conn.commit()
    conn.close()


def _rewritten() -> dict:
    conn = ms.connect()
    try:
        return {r["day"]: r["recorded_at"] for r in conn.execute("SELECT day, recorded_at FROM ledger_days")}
    finally:
        conn.close()


def test_a_day_a_missed_night_left_short_is_recorded_again(monkeypatch, capsys):
    from tests.test_ledger_ratio_1688 import _ccusage
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    _ccusage(monkeypatch)
    short, settled = _day(4), _day(5)
    _ledger_rows({short: ledger.day_start(_day(3)) - 3600, settled: ledger.day_start(_day(3)) + 3600})
    before = _rewritten()
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 0
    capsys.readouterr()
    after = _rewritten()
    assert after[short] > before[short], "written only before it ended, so its last hour was never counted"
    assert after[settled] == before[settled], "rewritten after the next day ended: settled, left alone"
