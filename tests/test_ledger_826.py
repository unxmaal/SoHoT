"""soh ledger: ccusage tokens, statusline readings, gateway purpose, displaced tokens, energy, privacy (#826, #976)."""
from __future__ import annotations

import io
import json
import plistlib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import cli, ledger, statusline
from harness import memory_store as ms
from tests import shells

FIX = Path(__file__).parent / "fixtures" / "ledger"
REPO = Path(__file__).resolve().parents[1]
UTC = timezone.utc


def at(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()


def ccusage_doc() -> dict:
    return json.loads((FIX / "ccusage-daily.json").read_text(encoding="utf-8"))


def build(**kw):
    args = dict(since=at("2026-10-08", 0), now=at("2026-10-10", 23), cloud_doc={"available": False},
                rows=[], limits=[], power=[], tz=UTC)
    args.update(kw)
    return ledger.build(**args)


# --- cloud ----------------------------------------------------------------------------------------

def test_ccusage_days_carry_tokens_in_all_and_by_model():
    got = ledger.parse_ccusage(ccusage_doc())
    d8 = got["days"]["2026-10-08"]
    assert d8["tokens"] == {"input": 1000, "output": 2000, "cache_write": 3000, "cache_read": 4000}
    assert d8["models"]["claude-sonnet-5-5"] == {"input": 100, "output": 500, "cache_read": 0, "cache_write": 0}
    assert "usd" not in json.dumps(got) and "unpriced" not in json.dumps(got)


def test_the_cloud_total_is_the_sum_of_each_days_tokens():
    doc = {"available": True, "source": "ccusage@x", **ledger.parse_ccusage(ccusage_doc())}
    L = build(cloud_doc=doc)
    assert L["cloud"]["tokens"] == {"input": 1015, "output": 2027, "cache_read": 4000, "cache_write": 3000}
    assert [d["cloud"]["tokens"]["output"] for d in L["days"]] == [2000, 20, 7]


def test_ccusage_runs_at_the_pin_in_calculate_offline_mode():
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, json.dumps(ccusage_doc()), "")

    got = ledger.cloud("2026-10-08", runner=runner, which=lambda n: "/x/npx")
    pin = ledger.pin("CCUSAGE_PIN").split("==")[1]
    assert ledger.pin("CCUSAGE_PIN").startswith("ccusage==") and re.fullmatch(r"\d+\.\d+\.\d+", pin)
    assert seen["argv"] == ["npx", "-y", f"ccusage@{pin}", "daily", "--json", "--mode", "calculate",
                            "--offline", "--since", "20261008"]
    assert got["available"] and sorted(got["days"]) == ["2026-10-08", "2026-10-09", "2026-10-10"]


def test_without_npx_the_cloud_is_unavailable_not_zero():
    got = ledger.cloud("2026-10-08", runner=None, which=lambda n: None)
    assert got["available"] is False
    assert build(cloud_doc=got)["cloud"]["tokens"] is None


# --- local and displaced --------------------------------------------------------------------------

def row(day, purpose, pin_, pout, alias="sohot-code", lane="code", client="python-httpx"):
    return (at(day), alias, lane, client, purpose, pin_, pout)


def test_work_is_displaced_in_tokens_by_lane():
    rows = [row("2026-10-08", "work", 1_000_000, 100_000),
            row("2026-10-08", "work", 1_000_000, 0, "sohot-web", "web")]
    L = build(rows=rows)
    assert L["displaced"]["tokens"] == {"requests": 2, "input": 2_000_000, "output": 100_000}
    by = {x["lane"]: x for x in L["days"][0]["displaced"]["lanes"]}
    assert by["code"] == {"lane": "code", "requests": 1, "input": 1_000_000, "output": 100_000}
    assert "usd" not in json.dumps(L["displaced"]) and "tier" not in json.dumps(L["days"][0]["displaced"])


def test_finding_469_maps_to_work_tokens():
    rows = [row("2026-10-09", "unknown", 70_600_000, 8_600_000, "eval-7b", "", "Python-urllib")]
    assert build(rows=rows)["mapped"]["tokens"] == {"requests": 1, "input": 70_600_000, "output": 8_600_000}


def test_eval_and_smoke_are_cost_and_never_displaced():
    rows = [row("2026-10-08", "eval", 5_000_000, 500_000), row("2026-10-08", "smoke", 10, 5)]
    L = build(rows=rows)
    assert L["displaced"]["tokens"]["requests"] == 0
    assert L["days"][0]["cost"] == {"eval": {"requests": 1, "input": 5_000_000, "output": 500_000},
                                    "smoke": {"requests": 1, "input": 10, "output": 5}}


def test_unknown_rows_stay_apart_and_the_mapping_is_bounded_by_its_days():
    rows = [row("2026-10-08", "unknown", 100, 10, "eval-7b", ""),
            row("2026-10-12", "unknown", 100, 10, "eval-7b", ""),
            row("2026-10-08", "unknown", 7, 3, "mystery", ""),
            row("2026-10-08", "eval", 100, 10, "eval-7b", "")]
    L = build(rows=rows, now=at("2026-10-12", 23))
    d8 = L["days"][0]
    assert d8["unknown"] == {"requests": 1, "input": 7, "output": 3}
    assert [m["requests"] for m in d8["mapped"]["rows"]] == [1]
    assert "eval-7b -> work" in d8["mapped"]["rows"][0]["mapping"]
    assert L["days"][-1]["unknown"] == {"requests": 1, "input": 100, "output": 10}
    assert d8["cost"]["eval"]["requests"] == 1
    assert L["displaced"]["tokens"]["requests"] == 0
    assert L["mapped"]["note"].startswith("untagged history assigned by the alias mapping")


def test_a_delegation_is_counted_once_through_its_call_id():
    rows = [row("2026-10-08", "work", 1_000_000, 0) + ("local-a",),
            row("2026-10-08", "work", 1_000_000, 0, alias="imajev", lane="") + ("gw-b",),
            row("2026-10-08", "work", 1_000_000, 0) + ("",)]
    dels = [("local-a", at("2026-10-08"), "code", "used", 1_000_000, 0),
            ("gw-b", at("2026-10-08"), "decide", None, 1_000_000, 0),
            ("local-c", at("2026-10-09"), "code", "discarded", 500, 50)]
    L = build(rows=rows, delegations=dels)
    assert L["displaced"]["tokens"] == {"requests": 3, "input": 3_000_000, "output": 0}
    assert L["local"]["work"] == {"requests": 3, "input": 3_000_000, "output": 0}
    assert L["delegated"]["requests"] == 2
    assert L["delegated"]["outcomes"] == {"used": 1, "pending": 1}
    assert L["delegated"]["unjoined"] == {"requests": 1, "input": 500, "output": 50}
    assert L["days"][1]["displaced"]["tokens"]["requests"] == 0


def test_the_delegations_table_is_read_from_the_store_and_joins_the_gateway_row():
    from harness import delegations
    conn = ms.connect()
    try:
        conn.execute("INSERT INTO gateway_requests (at, alias, lane, client, purpose, prompt_tokens, "
                     "completion_tokens, call_id) VALUES (?, 'sohot-code', 'code', 'soh-delegate', 'work', 100, 10, "
                     "'local-x')", (at("2026-10-08"),))
        conn.commit()
        delegations.record(conn, "local-x", "code", prompt_tokens=100, completion_tokens=10, at=at("2026-10-08"))
        L = build(rows=ledger.gateway_rows(conn, 0), delegations=ledger.delegation_rows(conn, 0))
    finally:
        conn.close()
    assert L["delegated"]["requests"] == 1 and L["delegated"]["unjoined"]["requests"] == 0
    assert L["local"]["work"]["requests"] == 1


def test_a_store_before_schema_68_reads_every_row_as_unknown(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE gateway_requests (id INTEGER PRIMARY KEY, at REAL, alias TEXT, lane TEXT, "
              "client TEXT, prompt_tokens INTEGER, completion_tokens INTEGER)")
    c.execute("INSERT INTO gateway_requests VALUES (1, ?, 'a', '', 'c', 5, 6)", (at("2026-10-08"),))
    c.commit()
    c.close()
    conn = ledger.open_ro(db)
    assert ledger.gateway_rows(conn, 0) == [(at("2026-10-08"), "a", "", "c", "unknown", 5, 6, "")]
    assert ledger.delegation_rows(conn, 0) == []
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO gateway_requests (at) VALUES (1)")


# --- plan headroom --------------------------------------------------------------------------------

def statusline_inputs() -> list[dict]:
    return [json.loads(x) for x in (FIX / "statusline.jsonl").read_text(encoding="utf-8").splitlines()]


def test_the_statusline_logs_only_the_rate_limits(tmp_path):
    env = {"LOCALHARNESS_HOME": str(tmp_path)}
    out = io.StringIO()
    statusline.main(io.StringIO(json.dumps(statusline_inputs()[0])), out, env, now=1000.0)
    assert out.getvalue() == "Opus 5.5 | 5h 23% | 7d 41%\n"
    text = (tmp_path / "ledger" / "ratelimits.jsonl").read_text(encoding="utf-8")
    assert json.loads(text) == {"at": 1000.0, "five_hour": 23.4, "five_hour_resets_at": "2026-10-08T15:00:00Z",
                                "seven_day": 41.0, "seven_day_resets_at": "2026-10-12T09:00:00Z"}
    assert "HOME_MARK" not in text and "s-1" not in text


def test_the_statusline_skips_an_unchanged_reading_until_the_gap_passes(tmp_path):
    env = {"LOCALHARNESS_HOME": str(tmp_path)}
    first, second, bare = statusline_inputs()
    for data, now in ((first, 1000.0), (first, 1010.0), (second, 1020.0), (second, 1020.0 + statusline.MIN_GAP_S)):
        statusline.main(io.StringIO(json.dumps(data)), io.StringIO(), env, now=now)
    lines = (tmp_path / "ledger" / "ratelimits.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["at"] for x in lines] == [1000.0, 1020.0, 1020.0 + statusline.MIN_GAP_S]
    out = io.StringIO()
    statusline.main(io.StringIO(json.dumps(bare)), out, env, now=5000.0)
    assert out.getvalue() == "Opus 5.5\n"
    out = io.StringIO()
    statusline.main(io.StringIO("not json"), out, env, now=5000.0)
    assert out.getvalue() == "claude\n"
    assert len((tmp_path / "ledger" / "ratelimits.jsonl").read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:LOCALHARNESS_HOME")
def test_the_statusline_writes_where_the_ledger_reads(monkeypatch, tmp_path):
    import os
    from harness import paths
    assert statusline.store_path(os.environ) == ledger.ledger_dir() / "ratelimits.jsonl"
    monkeypatch.delenv(paths.ENV_VAR)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(paths, "DEFAULT_HOME", tmp_path / "localharness")
    assert statusline.store_path(os.environ) == ledger.ledger_dir() / "ratelimits.jsonl"


def test_the_statusline_script_runs_the_module_standalone(tmp_path):
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "statusline.sh")],
                          input=json.dumps(statusline_inputs()[1]), capture_output=True, text=True,
                          env={"PATH": __import__("os").environ["PATH"], "HOME": str(tmp_path),
                               "LOCALHARNESS_HOME": str(tmp_path / "lh")}, timeout=120)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "Opus 5.5 | 5h 72% | 7d 44%\n"
    assert (tmp_path / "lh" / "ledger" / "ratelimits.jsonl").exists()


def test_headroom_gives_the_latest_reading_and_each_days_peak():
    samples = [{"at": at("2026-10-08", 9), "five_hour": 20.0, "seven_day": 40.0},
               {"at": at("2026-10-08", 10), "five_hour": 80.0, "seven_day": 42.0},
               {"at": at("2026-10-09", 10), "five_hour": 5.0, "seven_day": 50.0}]
    L = build(limits=samples)
    assert L["headroom"]["latest"]["seven_day"] == 50.0 and L["headroom"]["samples"] == 3
    assert L["days"][0]["headroom"] == {"five_hour": 80.0, "seven_day": 42.0}
    assert not build()["headroom"]["available"]


# --- energy ---------------------------------------------------------------------------------------

def macmon_lines() -> list[str]:
    return (FIX / "macmon.jsonl").read_text(encoding="utf-8").splitlines()


def test_a_power_sample_is_one_macmon_reading_with_system_power_first(tmp_path):
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, macmon_lines()[len(seen) - 1] + "\n", "")

    path = tmp_path / "power.jsonl"
    a = ledger.sample_power(runner=runner, which=lambda n: "/x/macmon", now=at("2026-10-08", 12), path=path)
    b = ledger.sample_power(runner=runner, which=lambda n: "/x/macmon", now=at("2026-10-08", 12) + 60, path=path)
    assert seen[0] == ["macmon", "pipe", "-s", "1", "-i", str(ledger.POWER_WINDOW_MS)]
    assert (a["watts"], b["watts"]) == (100.0, 142.5)
    assert len(ledger.read_jsonl(path)) == 2


def test_without_macmon_the_sampler_and_the_ledger_say_energy_is_unavailable(tmp_path):
    got = ledger.sample_power(runner=None, which=lambda n: None, path=tmp_path / "p.jsonl")
    assert got == {"ok": False, "why": "macmon is not installed (brew install macmon)"}
    e = build(macmon=False)["energy"]
    assert e["available"] is False and e["why"].startswith("energy unavailable: macmon is not installed")


def test_energy_is_the_trapezoid_of_covered_time_times_the_tariff():
    t0 = at("2026-10-08", 12)
    samples = [{"at": t0, "watts": 100.0}, {"at": t0 + 60, "watts": 200.0}, {"at": t0 + 120, "watts": 100.0},
               {"at": t0 + 120 + ledger.POWER_GAP_S + 1, "watts": 900.0}]
    L = build(power=samples, tariff=0.5, macmon=True)
    e = L["energy"]
    assert e["kwh"] == pytest.approx(18000 / 3.6e6)
    assert e["covered_s"] == 120 and e["mean_watts"] == pytest.approx(150.0)
    assert e["usd"] == pytest.approx(18000 / 3.6e6 * 0.5) and e["tariff_usd_per_kwh"] == 0.5
    assert L["days"][0]["energy"]["kwh"] == pytest.approx(0.005)


# --- the daily table and the --json contract ------------------------------------------------------

def test_record_upserts_one_row_per_day():
    conn = ms.connect()
    try:
        L = build(rows=[row("2026-10-08", "work", 1_000_000, 0)])
        assert ledger.record(conn, L, 1.0) == 3
        assert ledger.record(conn, L, 2.0) == 3
        got = ledger.recorded(conn, "2026-10-08")
    finally:
        conn.close()
    assert [r["day"] for r in got] == ["2026-10-08", "2026-10-09", "2026-10-10"]
    assert got[0]["recorded_at"] == 2.0 and set(got[0]) == {"day", "recorded_at", "energy_kwh", "cloud_tokens"}


SECRET = "sk-THIS-IS-A-KEY-0123456789"
PROMPT = "PROMPT-MARKER the user asked about their tax return"


def test_ledger_json_is_aggregates_only(monkeypatch, capsys, tmp_path, _home):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    conn = ms.connect()
    conn.execute("INSERT INTO gateway_requests (at, alias, lane, served, spec, client, purpose, prompt_tokens, "
                 "completion_tokens) VALUES (?, 'sohot-code', 'code', ?, ?, ?, 'work', 1000, 100)",
                 (at("2026-10-09"), f"{fake_home}/models/x.gguf", f"llamacpp:{fake_home}/x", SECRET))
    rid = conn.execute("SELECT max(id) FROM gateway_requests").fetchone()[0]
    conn.execute("INSERT INTO gateway_samples VALUES (?, ?, ?)", (rid, PROMPT, PROMPT))
    conn.commit()
    conn.close()
    lines = [x.replace("HOME_MARK", json.dumps(str(fake_home))[1:-1]) for x in (FIX / "statusline.jsonl").read_text(encoding="utf-8").splitlines()]
    for i, x in enumerate(lines):
        statusline.main(io.StringIO(x), io.StringIO(), {"LOCALHARNESS_HOME": str(_home)}, now=at("2026-10-09") + i * 400)
    (_home / "ledger" / "power.jsonl").write_text(
        "".join(json.dumps({"at": at("2026-10-09") + i * 60, "watts": 100.0}) + "\n" for i in range(3)), encoding="utf-8")

    real = ledger.cloud

    def fake_cloud(first_day, **kw):
        return real(first_day, runner=lambda argv, **k: subprocess.CompletedProcess(
            argv, 0, json.dumps(ccusage_doc()), ""), which=lambda n: "/x/npx")

    monkeypatch.setattr(ledger, "cloud", fake_cloud)
    assert cli.main(["ledger", "--since", "2026-10-08", "--json"]) == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    for key in ("window", "assumptions", "cloud", "headroom", "local", "delegated", "displaced", "mapped",
                "energy", "days"):
        assert key in doc
    assert doc["cloud"]["tokens"]["input"] == 1015
    assert doc["local"]["work"] == {"requests": 1, "input": 1000, "output": 100}
    assert doc["displaced"]["tokens"] == {"requests": 1, "input": 1000, "output": 100}
    assert doc["energy"]["samples"] == 3 and doc["headroom"]["samples"] == 2
    for leak in (str(fake_home), str(_home), str(tmp_path), SECRET, "sk-", "PROMPT-MARKER", "secret-project", "s-1"):
        assert leak not in out, leak


def test_the_text_report_counts_claude_in_tokens(monkeypatch, capsys):
    monkeypatch.setattr(ledger, "cloud", lambda first_day, **kw: {
        "available": True, "source": "ccusage@x", **ledger.parse_ccusage(ccusage_doc())})
    assert cli.main(["ledger", "--since", "2026-10-08"]) == 0
    out = capsys.readouterr().out
    assert "cloud     1,015 in, 2,027 out, 4,000 cache read, 3,000 cache write (ccusage@x)" in out
    assert "energy unavailable" in out or "no power samples" in out


# --- launchd units: generated only, under a fake HOME ---------------------------------------------

def _generate(tmp_path, **extra):
    import os
    out = tmp_path / "agents"
    env = {k: v for k, v in os.environ.items() if k != "LH_ROLE"}
    env.update(HOME=str(tmp_path / "home"), LOCALHARNESS_HOME=str(tmp_path / "lh"), **extra)
    proc = subprocess.run([shells.BASH, str(REPO / "scripts" / "launchd.sh"), "generate", str(out)],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    return {p.stem.rsplit(".", 1)[-1]: plistlib.loads(p.read_bytes()) for p in out.glob("*.plist")}


def test_the_energy_unit_samples_every_minute_on_every_role(tmp_path):
    units = _generate(tmp_path)
    e = units["energy"]
    assert e["ProgramArguments"][1].endswith("serve-energy.sh")
    assert [c["Minute"] for c in e["StartCalendarInterval"]] == list(range(60))
    assert "KeepAlive" not in e and "RunAtLoad" not in e
    assert "energy" in _generate(tmp_path / "n", LH_ROLE="node")


def test_the_ledger_unit_records_nightly_on_the_scheduler_only(tmp_path):
    units = _generate(tmp_path)
    assert units["ledger"]["StartCalendarInterval"] == [{"Hour": 23, "Minute": 0}]
    assert "ledger" not in _generate(tmp_path / "n", LH_ROLE="node")
    text = (REPO / "scripts" / "serve-ledger.sh").read_text(encoding="utf-8")
    assert "uv run soh ledger --since 2d --record" in text


def test_the_energy_script_exits_quietly_without_macmon():
    text = (REPO / "scripts" / "serve-energy.sh").read_text(encoding="utf-8")
    assert "command -v macmon" in text and "exit 0" in text and "soh ledger --sample-power" in text
