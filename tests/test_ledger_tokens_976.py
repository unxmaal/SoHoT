"""Claude Code usage is reported in tokens and plan-window use, never dollars, on a Max-plan login. #976."""
from __future__ import annotations

import json
import subprocess
import warnings
from datetime import datetime

import pytest

from harness import cli, ledger, morning, otel, trends
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests import dollar_scan
from tests.test_morning_867 import _beat, _gh, _git

FIX = ledger.paths.REPO / "tests" / "fixtures" / "ledger"


def local(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").timestamp()


def _ccusage(monkeypatch):
    doc = json.loads((FIX / "ccusage-daily.json").read_text(encoding="utf-8"))
    real = ledger.cloud

    def fake(first_day, **kw):
        return real(first_day, runner=lambda argv, **k: subprocess.CompletedProcess(argv, 0, json.dumps(doc), ""),
                    which=lambda n: "/x/npx")
    monkeypatch.setattr(ledger, "cloud", fake)
    monkeypatch.setattr(ledger, "prices", lambda pin: {"claude-sonnet-5-5": [2e-06, 1e-05]}, raising=False)


def _work_row(day: str):
    conn = ms.connect()
    conn.execute("INSERT INTO gateway_requests (at, alias, lane, client, purpose, prompt_tokens, completion_tokens) "
                 "VALUES (?, 'sohot-code', 'code', 'python-httpx', 'work', 1000000, 100000)", (local(day),))
    conn.commit()
    conn.close()


def _usd_paths(doc, path=""):
    if isinstance(doc, dict):
        for k, v in doc.items():
            p = f"{path}.{k}"
            if "usd" in k.lower() or "tier" == k:
                yield p
            yield from _usd_paths(v, p)
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            yield from _usd_paths(v, f"{path}[{i}]")


def test_the_ledger_reports_claude_usage_in_tokens_and_prints_no_dollar(monkeypatch, capsys):
    _ccusage(monkeypatch)
    _work_row("2026-10-08")
    assert cli.main(["ledger", "--since", "2026-10-08"]) == 0
    out = capsys.readouterr().out
    assert "$" not in out, [ln for ln in out.splitlines() if "$" in ln]
    assert "cloud     1,015 in, 2,027 out, 4,000 cache read, 3,000 cache write" in out
    assert "displaced 1.00M in, 100,000 out of tagged work" in out


def test_the_ledger_json_carries_tokens_and_no_dollar_field_but_energy(monkeypatch, capsys):
    _ccusage(monkeypatch)
    _work_row("2026-10-08")
    assert cli.main(["ledger", "--since", "2026-10-08", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    bad = [p for p in _usd_paths(doc) if ".energy" not in p and "tariff_usd_per_kwh" not in p]
    assert bad == []
    assert doc["cloud"]["tokens"] == {"input": 1015, "output": 2027, "cache_read": 4000, "cache_write": 3000}
    d8 = next(d for d in doc["days"] if d["day"] == "2026-10-08")
    assert d8["cloud"]["models"]["claude-opus-5-5"] == {"input": 900, "output": 1500, "cache_read": 4000,
                                                         "cache_write": 3000}
    assert d8["displaced"]["tokens"] == {"requests": 1, "input": 1_000_000, "output": 100_000}


def test_morning_shows_last_nights_ledger_in_tokens_and_no_dollar(monkeypatch, capsys, tmp_path):
    _ccusage(monkeypatch)
    _work_row("2026-10-08")
    ledger.ledger_dir().mkdir(parents=True, exist_ok=True)
    (ledger.ledger_dir() / "ratelimits.jsonl").write_text(
        json.dumps({"at": local("2026-10-08", 9), "five_hour": 80.0, "seven_day": 44.0}) + "\n", encoding="utf-8")
    assert cli.main(["ledger", "--since", "2026-10-08", "--record"]) == 0
    capsys.readouterr()
    now = local("2026-10-09", 6)
    d = tmp_path / "deploy"
    (d / ".git").mkdir(parents=True)
    conn = ms.connect()
    try:
        r = morning.gather(conn, now, now - 18 * 3600, beat=_beat(), gh=_gh(), git=_git(0), where=d,
                           lanes=lambda c: [])
    finally:
        conn.close()
    text = "\n".join(morning_cmd.render(r))
    line = next(ln for ln in text.splitlines() if ln.startswith("ledger"))
    assert "$" not in text, line
    assert line.startswith("ledger    2026-10-08: cloud 1,000 in, 2,000 out, 4,000 cache read, 3,000 cache write (at least, ccusage); "
                           "plan peak 5h 80%, 7d 44%; displaced 1.00M in, 100,000 out"), line


def test_a_ledger_row_from_before_976_reads_its_tokens_from_the_detail():
    conn = ms.connect()
    detail = {"cloud": {"usd": 35.76, "tokens": {"input": 5, "output": 6, "cache_read": 7, "cache_write": 8}},
              "headroom": {"seven_day": 41.0},
              "displaced": {"usd": 3.0, "lanes": [{"lane": "code", "requests": 2, "input": 10, "output": 20,
                                                   "usd": 3.0, "tier": "sonnet ($2.00/$10.00 per M in/out)"}]}}
    now = local("2026-10-15", 6)
    conn.execute("INSERT INTO ledger_days (day, recorded_at, energy_kwh, detail) VALUES ('2026-10-14', ?, 0.06, ?)",
                 (now - 3600, json.dumps(detail)))
    conn.commit()
    got = morning.ledger_row(conn, now)
    conn.close()
    assert got["cloud"] == {"input": 5, "output": 6, "cache_read": 7, "cache_write": 8}
    assert got["displaced"] == {"requests": 2, "input": 10, "output": 20}
    assert got["plan"] == {"seven_day": 41.0}
    assert "$" not in morning_cmd.ledger_line(got)


LEDGER_DAYS_76 = """
CREATE TABLE ledger_days (
    day           TEXT PRIMARY KEY,
    recorded_at   REAL NOT NULL,
    -- NULL when ccusage did not run; unpriced models are never in it.
    cloud_usd     REAL,
    displaced_usd REAL,
    mapped_usd    REAL,
    -- The counterfactual tier the displaced figure assumed.
    tier          TEXT NOT NULL DEFAULT '',
    energy_kwh    REAL,
    -- JSON: the day as `soh ledger --json` gives it.
    detail        TEXT NOT NULL DEFAULT '{}'
);
"""


def test_schema_77_drops_the_dollar_columns_and_keeps_each_day(old_store):
    path = old_store(76, ddl=LEDGER_DAYS_76, rows=(
        "INSERT INTO ledger_days (day, recorded_at, cloud_usd, tier, energy_kwh, detail) "
        "VALUES ('2026-10-17', 1.0, 238.3, 'sonnet', 0.24, '{\"cloud\": {\"usd\": 238.3}}');"))
    conn = ms.connect(path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ledger_days)")}
        row = dict(conn.execute("SELECT * FROM ledger_days").fetchone())
    finally:
        conn.close()
    assert not cols & {"cloud_usd", "displaced_usd", "mapped_usd", "tier"}
    assert row["energy_kwh"] == 0.24 and json.loads(row["detail"])["cloud"]["usd"] == 238.3


def test_a_stored_row_with_the_retired_cost_usd_metric_neither_warns_nor_ranks():
    from evals.core import Result, summarize
    rows = [Result(case_id="c", candidate="claude-code:claude-opus-5-5", passed=True, seconds=1.0, peak_kb=0,
                   detail="", metrics={"resolved": 1, "completion_tokens": 701, "cost_usd": 0.042756})]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s = summarize(rows)
    flat = json.dumps(s, default=str)
    assert "cost_usd" not in flat
    assert "completion_tokens" in flat


def test_the_trend_charts_plot_claude_in_tokens():
    detail = {"cloud": {"models": {"claude-opus-5-5": {"usd": 9.0, "tokens": 100, "priced_by": "ccusage"}},
                        "tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4}},
              "displaced": {"lanes": [{"lane": "code", "input": 10, "output": 5}], "usd": 2.0}}
    rows = [{"day": "2026-10-14", "energy_kwh": None, "detail": detail},
            {"day": "2026-10-15", "energy_kwh": None,
             "detail": {"cloud": {"tokens": {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}}}}]
    cloud, displaced = trends.cloud_chart(rows), trends.displaced_chart(rows)
    assert cloud["unit"] == displaced["unit"] == "tokens"
    assert cloud["series"]["claude-opus-5-5"] == {"2026-10-14": 100.0}
    assert cloud["series"]["all models (recorded before #827)"] == {"2026-10-15": 2.0}
    assert displaced["series"] == {"code": {"2026-10-14": 15.0}}
    assert "$" not in json.dumps([cloud, displaced])


def test_ledger_compare_has_no_cost_row_and_lists_models_by_tokens():
    ev = [{"name": "api_request", "model": "claude-opus-5-5", "cost_usd": 0.5, "input_tokens": 10,
           "output_tokens": 20, "cache_read_tokens": 30, "cache_creation_tokens": 40,
           "cache_creation_5m_tokens": 40, "cache_creation_1h_tokens": 0, "session_id": "s"}]
    C = otel.compare("2026-10-14", ev, [], None, [], ccusage_available=False)
    assert "usd" not in {r["row"] for r in C["rows"]}
    assert C["models"] == [{"model": "claude-opus-5-5", "otel_events": 100, "otel_metrics": None, "ccusage": None}]


# --- the scanner ----------------------------------------------------------------------------------

POSITIVE = '''
def _usd(v):
    return "n/a" if v is None else f"${v:,.2f}"

def show(L):
    note(f"cloud     {_usd(spend)} for Claude Code")
    note(f"opus at ${rate:.2f} per M tokens")
    title = "Cloud API-equivalent dollars by model"
    line = "spent $%.2f on claude" % x
'''

NEGATIVE = '''
def _usd(v):
    """Dollars, formatted; cloud cost lives elsewhere."""
    return f"${v:,.2f}"

def show(e, root):
    note(f"energy    {e['kwh']:.2f} kWh, {_usd(e['usd'])} at ${e['tariff']}/kWh")
    note(f"set ${ENV_TOKEN} to change the home")
    note(f"cloud     {tok(c['input'])} in, {tok(c['output'])} out")
'''


def test_the_scanner_flags_each_dollar_beside_claude_usage():
    hits = dollar_scan.scan_source(POSITIVE)
    assert [h.line for h in hits] == [6, 7, 8, 9], hits


def test_the_scanner_passes_electricity_shell_variables_and_token_counts():
    assert dollar_scan.scan_source(NEGATIVE) == []


@pytest.mark.parametrize("root", ["repo"])
def test_no_output_string_prices_claude_usage_in_dollars(root):
    assert [f"{h.module}:{h.line}: {h.text}" for h in dollar_scan.scan()] == []
