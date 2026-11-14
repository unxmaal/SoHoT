"""#1941: `soh ledger --day` rewrites a named day last written before it settled, once, and refuses one still open."""
import json
import time

import pytest

from harness import cli, ledger, paths
from harness import memory_store as ms
from tests.test_ledger_ratio_1688 import _ccusage, _rows


def _day(days_ago: int) -> str:
    return ledger.days_between(time.time() - days_ago * 86400, time.time())[0]


def _stored(day: str, at: float, local: int = 0) -> None:
    conn = ms.connect()
    conn.execute("INSERT INTO ledger_days (day, recorded_at, energy_kwh, detail) VALUES (?, ?, NULL, ?)",
                 (day, at, json.dumps({"ratio": {"local": local, "cloud": None}})))
    conn.commit()
    conn.close()


def _written() -> dict:
    conn = ms.connect()
    try:
        return {r["day"]: (r["recorded_at"], json.loads(r["detail"])["ratio"]["local"])
                for r in conn.execute("SELECT day, recorded_at, detail FROM ledger_days")}
    finally:
        conn.close()


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())
    _ccusage(monkeypatch)


def _late_on(day: str) -> float:
    return ledger.day_start(day) + 23 * 3600


def test_a_day_written_before_it_ended_is_rewritten_once(live, capsys):
    short = _day(6)
    _stored(short, _late_on(short), local=100)
    _rows((_late_on(short) + 1800, "sohot-decide", "decide", "internal", 4000, 2000))
    before = _written()[short]
    assert cli.main(["ledger", "--day", short, "--record"]) == 0
    out = capsys.readouterr().out
    first = _written()[short]
    assert first[0] > before[0] and first[1] == 6000, "its last hour landed after the write and is now counted"
    assert f"{short} short" in out and "before local 100" in out and "recount local 6,000" in out, out
    assert cli.main(["ledger", "--day", short, "--record"]) == 0
    assert f"{short} complete" in capsys.readouterr().out
    assert _written()[short] == first, "a second run finds the day complete and writes nothing"


def test_a_complete_day_is_left_alone(live, capsys):
    done = _day(6)
    _stored(done, ledger.settled_at(done) + 60, local=100)
    _rows((_late_on(done), "sohot-decide", "decide", "internal", 4000, 2000))
    before = _written()
    assert cli.main(["ledger", "--day", done, "--record"]) == 0
    assert f"{done} complete" in capsys.readouterr().out
    assert _written() == before


@pytest.mark.parametrize("ago", [0, 1])
def test_a_day_still_open_is_refused(live, capsys, ago):
    open_ = _day(ago)
    _stored(open_, time.time() - 60)
    before = _written()
    assert cli.main(["ledger", "--day", _day(6), "--day", open_, "--record"]) == 2
    assert f"{open_} is still open" in capsys.readouterr().out
    assert _written() == before


def test_without_record_the_recount_is_printed_and_nothing_written(live, capsys):
    short = _day(6)
    _stored(short, _late_on(short), local=100)
    _rows((_late_on(short) + 1800, "sohot-decide", "decide", "internal", 4000, 2000))
    before = _written()
    assert cli.main(["ledger", "--day", short]) == 0
    out = capsys.readouterr().out
    assert "recount local 6,000" in out and "dry run: 1 short day(s)" in out, out
    assert _written() == before


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/commands/ledger.py:cmd_days:gather")
def test_a_rewrite_from_a_home_that_is_not_the_live_one_is_refused(monkeypatch, capsys):
    _ccusage(monkeypatch)
    short = _day(6)
    _stored(short, _late_on(short), local=100)
    _rows((_late_on(short) + 1800, "sohot-decide", "decide", "internal", 4000, 2000))
    before = _written()
    assert cli.main(["ledger", "--day", short, "--record"]) == 1
    assert "not the live store" in capsys.readouterr().out
    assert _written() == before


def test_a_recount_below_the_stored_count_keeps_the_stored_row(live, capsys):
    short = _day(6)
    _stored(short, _late_on(short), local=10**6)
    before = _written()
    assert cli.main(["ledger", "--day", short, "--record"]) == 0
    assert f"{short} lower" in capsys.readouterr().out
    assert _written() == before


def test_a_range_rewrites_only_its_short_days(live, capsys):
    first, mid, last = _day(8), _day(7), _day(6)
    _stored(first, _late_on(first))
    _stored(mid, ledger.settled_at(mid) + 60)
    before = _written()
    assert cli.main(["ledger", "--day", f"{first}..{last}", "--record"]) == 0
    out = capsys.readouterr().out
    after = _written()
    assert after[first][0] > before[first][0]
    assert after[mid] == before[mid]
    assert last not in after and f"{last} unrecorded" in out, "a day with no row is reported, not invented"
    assert cli.main(["ledger", "--day", f"{last}..{first}"]) == 2


def test_a_row_written_before_the_ratio_was_stored_is_judged_by_its_cloud_tokens(live, capsys):
    old = _day(6)
    conn = ms.connect()
    conn.execute("INSERT INTO ledger_days (day, recorded_at, energy_kwh, detail) VALUES (?, ?, NULL, ?)",
                 (old, _late_on(old), json.dumps({"cloud": {"tokens": {"input": 10**9, "output": 5}}})))
    conn.commit()
    conn.close()
    assert cli.main(["ledger", "--day", old, "--record"]) == 0
    out = capsys.readouterr().out
    assert f"{old} lower" in out and "before local not counted cloud 1000.00M" in out, out
