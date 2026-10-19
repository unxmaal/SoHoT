"""Energy on macOS 27: 0 W is a reading, a CPU read as 0 W while active makes the day partial (#1005)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import pytest

from harness import cli, ledger, morning, trends
from harness import memory_store as ms
from harness.commands import ledger as ledger_cmd
from harness.commands import morning as morning_cmd

UTC = timezone.utc


def at(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()


def _run(stdout: str, rc: int = 0):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, rc, stdout, "")


def _sample(path, stdout, rc=0):
    return ledger.sample_power(runner=_run(stdout, rc), which=lambda n: "/x/macmon", now=at("2026-10-18"), path=path)


IDLE = {"all_power": 0.0, "sys_power": 0.0, "cpu_power": 0.0, "gpu_power": 0.0, "ane_power": 0.0,
        "cpu_active_ratio": 0.14, "gpu_active_ratio": 0.0}


def test_a_zero_reading_with_valid_json_is_stored_as_zero_watts(tmp_path):
    path = tmp_path / "power.jsonl"
    got = _sample(path, json.dumps(IDLE) + "\n")
    assert got["ok"] is True and got["watts"] == 0.0
    [row] = ledger.read_jsonl(path)
    assert row["watts"] == 0.0 and row["cpu_active_ratio"] == 0.14


def test_only_a_failed_run_or_no_json_is_a_miss(tmp_path):
    path = tmp_path / "power.jsonl"
    assert _sample(path, json.dumps(IDLE), rc=1) == {"ok": False, "why": "macmon exited 1"}
    assert _sample(path, "")["why"] == "macmon printed no JSON"
    assert _sample(path, "not json\n")["why"] == "macmon printed no JSON"
    assert _sample(path, json.dumps({"cpu_power": 1.0}))["why"] == "macmon JSON has no sys_power or all_power"
    assert not path.exists()


def test_watts_prefers_a_positive_system_figure_and_keeps_zero():
    assert ledger.watts({"sys_power": 100.0, "all_power": 62.5}) == 100.0
    assert ledger.watts({"sys_power": 0.0, "all_power": 142.5}) == 142.5
    assert ledger.watts({"sys_power": 0.0, "all_power": 0.0}) == 0.0
    assert ledger.watts({"sys_power": None, "all_power": None}) is None
    assert ledger.watts({"sys_power": True, "all_power": -1}) is None


def _day(day, cpu, ratio=0.14, gpu=20.0, n=60):
    return [{"at": at(day) + i * 60, "watts": cpu + gpu, "cpu_power": cpu, "gpu_power": gpu, "ane_power": 0.0,
             "all_power": cpu + gpu, "sys_power": cpu + gpu, "cpu_active_ratio": ratio} for i in range(n)]


def test_the_partial_check_fires_on_a_day_of_cpu_zero_while_active():
    e = ledger.energy(_day("2026-10-18", 0.0), 0, 0.15, True, UTC, macmon_version="0.8.2")
    d = e["days"]["2026-10-18"]
    assert e["partial"] and d["partial"] and e["kwh"] is None and d["kwh"] is None and e["usd"] is None
    assert d["lower_bound_kwh"] == pytest.approx(20.0 * 59 * 60 / 3.6e6)
    assert "CPU read 0 W on 60 of 60 samples" in e["why"] and "macmon 0.8.2" in e["why"] and "0.9.0" in e["why"]


def test_the_partial_check_stays_quiet_with_cpu_readings_or_an_idle_cpu():
    e = ledger.energy(_day("2026-10-18", 3.0), 0, 0.15, True, UTC, macmon_version="0.10.0")
    assert not e["partial"] and e["kwh"] == pytest.approx(23.0 * 59 * 60 / 3.6e6)
    assert ledger.energy(_day("2026-10-18", 0.0, ratio=0.0), 0, 0.15, True, UTC)["partial"] is False
    assert ledger.energy([{"at": at("2026-10-18") + i * 60, "watts": 9.0} for i in range(3)], 0, 0.15, True,
                         UTC)["partial"] is False


def test_the_threshold_is_a_share_of_the_day():
    some = _day("2026-10-18", 0.0, n=89) + _day("2026-10-18", 3.0, n=11)
    for i, s in enumerate(some):
        s["at"] = at("2026-10-18") + i * 60
    assert ledger.energy(some, 0, 0.15, True, UTC)["partial"] is False
    assert ledger.energy(some[:95], 0, 0.15, True, UTC)["partial"] is True


def test_a_newer_macmon_still_reading_zero_is_named_as_such():
    why = ledger.partial_why(9, 10, "0.10.0")
    assert "macmon 0.10.0 still reads no CPU power" in why and "--HEAD" not in why
    assert "macmon before 0.9.0" in ledger.partial_why(9, 10, None)


def test_a_counter_catching_up_is_not_power_drawn():
    s = _day("2026-10-18", 3.0, n=3)
    s[1].update(watts=16853.3, cpu_power=16851.0)
    e = ledger.energy(s, 0, 0.15, True, UTC)
    assert e["implausible"] == 1 and e["kwh"] == pytest.approx(23.0 * 120 / 3.6e6)


def test_macmon_version_is_parsed_from_its_banner():
    assert ledger.macmon_version(runner=_run("macmon 0.8.2\n"), which=lambda n: "/x") == "0.8.2"
    assert ledger.macmon_version(runner=_run(""), which=lambda n: "/x") is None
    assert ledger.macmon_version(runner=None, which=lambda n: None) is None


def _build(power):
    return ledger.build(since=at("2026-10-17", 0), now=at("2026-10-18", 23), cloud_doc={"available": False},
                        rows=[], limits=[], power=power, tz=UTC, macmon=True, macmon_version="0.8.2")


def test_a_partial_day_is_recorded_without_a_number_and_said_so_in_morning_and_trends():
    conn = ms.connect()
    try:
        ledger.record(conn, _build(_day("2026-10-17", 3.0) + _day("2026-10-18", 0.0)), at("2026-10-18", 23))
        rows = {r["day"]: r for r in conn.execute("SELECT day, energy_kwh FROM ledger_days")}
        assert rows["2026-10-18"]["energy_kwh"] is None and rows["2026-10-17"]["energy_kwh"] > 0
        led = morning.ledger_row(conn, at("2026-10-19", 9))
        line = morning_cmd.ledger_line(led)
        assert "energy PARTIAL, at least 0.02 kWh without the CPU (CPU read 0 W on 60 of 60 samples" in line
        chart = trends.energy_chart(trends.ledger_rows(conn, "2026-10-17"))
        assert set(chart["series"]["kWh"]) == {"2026-10-17"} and "1 days are left out" in chart["note"]
    finally:
        conn.close()


def test_the_text_report_prints_partial_not_a_total(capsys):
    L = _build(_day("2026-10-18", 0.0))
    ledger_cmd.show(L)
    out = capsys.readouterr().out
    assert "energy    PARTIAL: at least 0.02 kWh without the CPU" in out
    assert "SoC power (CPU, GPU, ANE)" in out
    assert "2026-10-18" in out and "partial" in out.split("2026-10-18")[-1]


def test_the_cli_passes_the_installed_macmon_version(monkeypatch, capsys, _home):
    monkeypatch.setattr(ledger, "cloud", lambda first_day, **kw: {"available": False, "why": "x"})
    monkeypatch.setattr(ledger, "macmon_version", lambda: "0.8.2")
    (_home / "ledger").mkdir(parents=True, exist_ok=True)
    (_home / "ledger" / "power.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in _day("2026-10-18", 0.0, n=3)), encoding="utf-8")
    assert cli.main(["ledger", "--since", "2026-10-18", "--json"]) == 0
    e = json.loads(capsys.readouterr().out)["energy"]
    assert e["partial"] and e["macmon"] == "0.8.2" and e["kwh"] is None
