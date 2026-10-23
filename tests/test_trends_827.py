"""Trend charts on the public page (#827), Claude Code usage in tokens (#976)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from harness import delegations, ledger, publish, site, trends
from harness import memory_store as ms

FIX = Path(__file__).parent / "fixtures" / "ledger"
UTC = timezone.utc
# privacy-ok: deliberate fixtures, the things the export must never carry.
USER, HOST = "patq", "patq-tower"
HOME = f"/Users/{USER}"  # privacy-ok
LEAKS = (USER, HOST, "/Users/", "/home/", ".local", "192.168.", "sk-")  # privacy-ok


def at(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()


def ccusage_doc() -> dict:
    return json.loads((FIX / "ccusage-daily.json").read_text(encoding="utf-8"))


# --- the ledger records what the charts need --------------------------------------------------

def _ledger(**kw):
    cloud = {"available": True, "source": "ccusage@x", **ledger.parse_ccusage(ccusage_doc())}
    rows = [(at("2026-10-09"), "sohot-code", "code", "python-httpx", "work", 1000, 100, ""),
            (at("2026-10-09"), "sohot-code", "code", "python-httpx", "eval", 500, 50, ""),
            (at("2026-10-08"), "eval-7b", "extract", "Python-urllib", None, 2000, 200, "")]
    ctx = [{"tool": "Bash", "tokens": 300, "at": at("2026-10-08"), "day": "2026-10-08"},
           {"tool": "Bash", "tokens": 100, "at": at("2026-10-09"), "day": "2026-10-09"},
           {"tool": "mcm-engine search", "tokens": 900, "at": at("2026-10-09"), "day": "2026-10-09"}]
    power = [{"at": at("2026-10-09") + i * 60, "watts": 120.0} for i in range(4)]
    args = dict(since=at("2026-10-08", 0), now=at("2026-10-10", 23), cloud_doc=cloud, rows=rows,
                limits=[], power=power, tz=UTC, context=ctx, macmon=True)
    args.update(kw)
    return ledger.build(**args)


def test_each_ledger_day_carries_cloud_by_model_and_context_by_tool():
    days = {d["day"]: d for d in _ledger()["days"]}
    assert days["2026-10-08"]["cloud"]["models"]["claude-sonnet-5-5"] == {"input": 100, "output": 500,
                                                                        "cache_read": 0, "cache_write": 0}
    assert days["2026-10-09"]["context"] == {"Bash": 100, "mcm-engine search": 900}
    assert days["2026-10-10"]["context"] == {}


@pytest.fixture
def store():
    conn = ms.connect()
    ledger.record(conn, _ledger(), at("2026-10-10", 23))
    for i, (lane, outcome) in enumerate([("code", "used"), ("code", "discarded"), ("code", "edited"),
                                         ("code", None), ("decide", "used")]):
        delegations.record(conn, f"c{i}", lane, at=at("2026-10-09"))
        if outcome:
            delegations.outcome(conn, f"c{i}", outcome, why=f"see {HOME}/notes.txt")  # privacy-ok
    yield conn
    conn.close()


LIMITS = [{"at": at("2026-10-09", 9), "five_hour": 12.0, "seven_day": 30.0},
          {"at": at("2026-10-09", 15), "five_hour": 55.0, "seven_day": 33.0},
          {"at": at("2026-10-10", 9), "five_hour": 8.0, "seven_day": 41.0}]


_REAL_GATHER = trends.gather


def _gather(conn, **kw):
    args = dict(days=10, limits=LIMITS, live_context={})
    args.update(kw)
    return _REAL_GATHER(conn, at("2026-10-10", 23), **args)


def test_every_chart_is_a_daily_series_keyed_by_name(store):
    t = _gather(store)
    assert t["first_day"] == trends._first_day(at("2026-10-10", 23), 10)
    c = t["charts"]
    assert set(c) == set(trends.ORDER)
    assert c["cloud"]["series"]["claude-opus-5-5"] == {"2026-10-08": 9400.0, "2026-10-09": 30.0}
    assert c["cloud"]["series"]["claude-sonnet-5-5"] == {"2026-10-08": 600.0}
    assert c["cloud"]["unit"] == "tokens"
    assert c["plan_cap"]["series"]["5-hour window, daily peak"] == {"2026-10-09": 55.0, "2026-10-10": 8.0}
    assert c["plan_cap"]["series"]["7-day window, daily peak"]["2026-10-10"] == 41.0
    assert c["local_tokens"]["series"]["work"] == {"2026-10-09": 1100.0}
    assert c["local_tokens"]["series"]["eval"] == {"2026-10-09": 550.0}
    assert c["local_tokens"]["series"]["work (alias mapping)"] == {"2026-10-08": 2200.0}
    assert c["displaced"]["series"] == {"code": {"2026-10-09": 1100.0}}
    assert c["energy"]["series"]["kWh"]["2026-10-09"] == pytest.approx(120 * 180 / 3.6e6, rel=1e-3)
    assert c["context"]["series"]["mcm-engine search"] == {"2026-10-09": 900.0}
    # code: used + edited of three closed; the pending one is in the label, not the rate.
    assert c["delegations"]["series"]["code"] == {"2026-10-09": pytest.approx(2 / 3, abs=1e-4)}
    assert "1 pending" in c["delegations"]["labels"]["code"]["2026-10-09"]
    assert c["delegations"]["series"]["decide"] == {"2026-10-09": 1.0}


def test_a_recorded_context_day_wins_and_the_transcripts_fill_the_rest(store):
    live = {"2026-10-09": {"Bash": 1}, "2026-10-07": {"Read": 40}}
    s = _gather(store, live_context=live)["charts"]["context"]["series"]
    assert s["Bash"] == {"2026-10-08": 300.0, "2026-10-09": 100.0}
    assert s["Read"] == {"2026-10-07": 40.0}


def test_an_empty_store_has_every_chart_and_no_series():
    conn = ms.connect()
    t = _gather(conn, limits=[])
    assert all(c["series"] == {} for c in t["charts"].values())
    assert not trends.has_data(t)


def test_more_series_than_hues_fold_into_other():
    series = {f"t{i}": {"2026-10-09": float(i)} for i in range(12)}
    got = trends.fold(series)
    assert len(got) == trends.MAX_SERIES and trends.OTHER in got
    assert got[trends.OTHER]["2026-10-09"] == sum(range(5))
    assert sum(v["2026-10-09"] for v in got.values()) == sum(range(12))


# --- privacy: aggregates only -----------------------------------------------------------------

@pytest.fixture
def _local(monkeypatch):
    monkeypatch.setattr(publish, "_local_names", lambda: [USER, HOST])


def test_the_export_carries_trends_that_pass_the_privacy_scanner(store, _local, monkeypatch):
    live = {"2026-10-10": {f"{HOME}/bin/tool": 5, f"mcp {HOST}.local probe": 7, "Bash": 9}}  # privacy-ok
    monkeypatch.setattr(trends, "gather", lambda conn, now, **kw: _gather(conn, live_context=live))
    doc = publish.export(store, now=at("2026-10-10", 23))
    assert doc["export_version"] == 4 and trends.has_data(doc["trends"])
    assert publish.findings(doc) == []
    publish.checked(doc)
    text = json.dumps(doc)
    for leak in LEAKS:
        assert leak not in json.dumps(doc["trends"]), leak
    assert "notes.txt" not in text and "infovore claims" not in text
    assert doc["trends"]["charts"]["context"]["series"][trends.OTHER] == {"2026-10-10": 12.0}


def test_the_ledger_mapping_and_outcome_reasons_never_reach_the_export(store, _local, monkeypatch):
    monkeypatch.setattr(trends, "gather", lambda conn, now, **kw: _gather(conn))
    t = json.dumps(publish.export(store, now=at("2026-10-10", 23))["trends"])
    for text in ("FINDING #469", "Python-urllib", "python-httpx", "see "):
        assert text not in t, text


def test_an_export_for_another_machine_carries_no_trends(store, _local):
    mid = ms.machine_row(store) or ms.remember_machine(store)
    assert "trends" not in publish.export(store, machine_id=mid, now=at("2026-10-10", 23))


# --- the page ---------------------------------------------------------------------------------

class _Parse(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.stack, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        if tag not in ("meta", "link", "br", "circle", "line", "polyline", "input", "img"):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in ("circle", "line", "polyline"):
            return
        assert self.stack and self.stack[-1] == tag, (tag, self.stack[-5:])
        self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)


def _machine(t):
    return {"machine": {"label": "Mac Studio M5 Ultra 96 GB", "slug": "mac-studio-m5-ultra-96-gb"},
            "generated_at": "2026-10-10T23:00:00Z", "lanes": [], "trends": t}


def test_the_trends_page_draws_each_chart_and_parses(store, tmp_path):
    t = _gather(store)
    doc = json.loads(json.dumps(_machine(t)))
    (tmp_path / "m.json").write_text(json.dumps(doc), encoding="utf-8")
    machines = publish.load(tmp_path)
    html = site.trends_page(machines, now=at("2026-10-10", 23))
    p = _Parse()
    p.feed(html)
    p.close()
    assert p.stack == []
    svgs = [a for tag, a in p.tags if tag == "svg" and "trend" in a.get("class", "")]
    drawn = [c for c in t["charts"].values() if c["series"]]
    assert len(svgs) == len(drawn) == 7
    assert 'id="trends"' in html and 'aria-current=page>Trends' in html
    bench = site.benchmarks(machines, now=at("2026-10-10", 23))
    assert 'id="trends"' not in bench and "<svg" not in bench, "trends stay off the benchmarks page (#849)"
    text = "".join(p.text)
    assert "claude-opus-5-5 2026-10-08: 9k" in text
    assert "Delegation acceptance by lane" in text


def test_annotations_inside_the_window_are_marked_and_others_are_left_out(store, monkeypatch):
    monkeypatch.setattr(trends, "ANNOTATIONS", (("2026-10-13", "change one"), ("2026-10-13", "change two")))
    inside = trends.gather(store, at("2026-10-14"), days=10, limits=[], live_context={})
    assert [a["day"] for a in inside["charts"]["context"]["annotations"]] == ["2026-10-13", "2026-10-13"]
    html = trends.render(inside)
    assert html.count('class="mark"') == 1
    assert "change one; change two" in html
    assert _gather(store)["charts"]["context"]["annotations"] == []


def test_the_annotation_is_drawn_on_its_day():
    chart = trends._chart("c", "tokens", {"Bash": {"2026-10-12": 900.0, "2026-10-14": 200.0}},
                          annotations=[{"day": "2026-10-13", "label": "rtk"}])
    out = trends.svg(chart)
    x = trends.LEFT + (trends.W - trends.LEFT - trends.RIGHT) / 2
    assert f'x1="{x:.1f}"' in out and ">rtk</text>" in out


def test_a_gap_day_breaks_the_line():
    chart = trends._chart("c", "tokens", {"m": {"2026-10-01": 1.0, "2026-10-02": 2.0, "2026-10-04": 3.0}})
    out = trends.svg(chart)
    assert out.count("<polyline") == 1 and out.count("<circle") == 3
    points = out.split('<polyline points="')[1].split('"')[0]
    assert len(points.split()) == 2


def test_a_page_with_no_trends_has_no_trends_window():
    html = site.benchmarks([_machine({"charts": {}})])
    assert 'id="trends"' not in html


def test_the_rendered_page_passes_the_privacy_scanner(store, tmp_path):
    from harness import privacy
    html = site.benchmarks([_machine(_gather(store))])
    assert privacy.scan(html, "page", publish.private_pattern()) == []
