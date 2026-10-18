"""Daily trend series for the public page: the ledger, plan caps, context and delegations over time. #827.

`gather` runs on the machine at publish and returns aggregates only. `render` runs on the Pages
runner with the standard library alone and draws each series as inline SVG.
"""
from __future__ import annotations

import datetime as _dt
import json
import re

#: How many days back the page charts.
TREND_DAYS = 90
#: Series beyond this many fold into "other"; the palette has eight validated hues.
MAX_SERIES = 8
#: (day, what changed): marked on the context chart as a before and after.
ANNOTATIONS = (
    ("2026-10-13", "rtk hook and bashOutputMaxChars 8000"),
    ("2026-10-14", "mcm-engine 3.12 search summaries"),
)
#: A tool, model, lane or purpose name the page may print; anything else is counted as "other".
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_ .,:+()#/-]{0,63}$")
OTHER = "other"
ORDER = ("cloud", "plan_cap", "local_tokens", "displaced", "energy", "context", "delegations")


# --- the data, on the machine ------------------------------------------------------------------

def _first_day(now: float, days: int) -> str:
    return (_dt.date.fromtimestamp(now) - _dt.timedelta(days=days - 1)).isoformat()


def _safe(name) -> str:
    name = str(name or "")
    return name if SAFE_NAME.match(name) and "/Users/" not in name and "/home/" not in name else OTHER


def _put(series: dict, name: str, day: str, value) -> None:
    if value is None:
        return
    s = series.setdefault(_safe(name), {})
    s[day] = round(s.get(day, 0) + float(value), 6)


def fold(series: dict, keep: int = MAX_SERIES) -> dict:
    """The `keep - 1` largest series by total, the rest summed into "other"."""
    if len(series) <= keep:
        return series
    ranked = sorted(series, key=lambda k: (k == OTHER, -sum(series[k].values()), k))
    out = {k: dict(series[k]) for k in ranked[:keep - 1] if k != OTHER}
    rest: dict = {}
    for k in series:
        if k not in out:
            for d, v in series[k].items():
                rest[d] = round(rest.get(d, 0) + v, 6)
    out[OTHER] = rest
    return out


def ledger_rows(conn, first_day: str) -> list[dict]:
    """ledger_days rows with their detail parsed; [] before schema 70."""
    import sqlite3
    try:
        rows = conn.execute("SELECT day, energy_kwh, detail FROM ledger_days WHERE day >= ? ORDER BY day",
                            (first_day,)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        r = dict(r)
        try:
            r["detail"] = json.loads(r.get("detail") or "{}")
        except ValueError:
            r["detail"] = {}
        out.append(r)
    return out


def delegation_rows(conn, since: float) -> list[tuple]:
    """(at, lane, outcome) per delegation since `since`; [] before schema 69."""
    import sqlite3
    try:
        return [tuple(r) for r in conn.execute(
            "SELECT at, lane, outcome FROM delegations WHERE at >= ?", (since,))]
    except sqlite3.OperationalError:
        return []


def _chart(title: str, unit: str, series: dict, note: str = "", **extra) -> dict:
    return {"title": title, "unit": unit, "series": series, "note": note, **extra}


def cloud_chart(rows: list[dict]) -> dict:
    """Claude Code tokens by model; a Max-plan login pays no per-token price, so none is charted. #976."""
    series: dict = {}
    for r in rows:
        cloud = r["detail"].get("cloud") or {}
        models = cloud.get("models") or {}
        if models:
            for name, m in models.items():
                n = m.get("tokens") if isinstance(m.get("tokens"), (int, float)) else \
                    sum(v for k, v in m.items() if k in ("input", "output", "cache_read", "cache_write"))
                _put(series, name, r["day"], n)
        elif cloud.get("tokens"):
            _put(series, "all models (recorded before #827)", r["day"], sum(cloud["tokens"].values()))
    return _chart("Claude Code tokens by model", "tokens", fold(series),
                  "Input, output and cache tokens from ccusage; the plan-cap chart is what the subscription counts.")


def plan_chart(samples: list[dict], since: float) -> dict:
    from harness import ledger
    days = ledger.headroom(samples, since).get("days") or {}
    series: dict = {}
    for day, d in sorted(days.items()):
        _put(series, "5-hour window, daily peak", day, d.get("five_hour"))
        _put(series, "7-day window, daily peak", day, d.get("seven_day"))
    return _chart("Plan cap used", "pct", series, "Peak of each day's statusline readings.")


def local_chart(rows: list[dict]) -> dict:
    series: dict = {}
    for r in rows:
        for purpose, b in (r["detail"].get("local") or {}).items():
            _put(series, purpose, r["day"], (b.get("input") or 0) + (b.get("output") or 0))
        for m in (r["detail"].get("mapped") or {}).get("rows") or []:
            _put(series, f"{m.get('purpose') or 'unknown'} (alias mapping)", r["day"],
                 (m.get("input") or 0) + (m.get("output") or 0))
    return _chart("Local tokens by purpose", "tokens", fold(series),
                  "Gateway tokens in and out. Work is what local displaced; eval and smoke are its cost.")


def displaced_chart(rows: list[dict]) -> dict:
    series: dict = {}
    for r in rows:
        for b in (r["detail"].get("displaced") or {}).get("lanes") or []:
            _put(series, b.get("lane") or "unlaned", r["day"], (b.get("input") or 0) + (b.get("output") or 0))
    return _chart("Displaced tokens by lane", "tokens", fold(series),
                  "Tagged work served locally instead of by Claude, tokens in and out.")


def energy_chart(rows: list[dict]) -> dict:
    series: dict = {}
    labels: dict = {}
    for r in rows:
        e = r["detail"].get("energy") or {}
        kwh = r.get("energy_kwh") if r.get("energy_kwh") is not None else e.get("kwh")
        if kwh is None:
            continue
        _put(series, "kWh", r["day"], kwh)
        if e.get("usd") is not None:
            labels.setdefault("kWh", {})[r["day"]] = f"${e['usd']:.2f}"
    return _chart("Energy, kWh per day", "kwh", series, "macmon whole-system power, integrated per day; "
                  "the dollar figure at the ledger's tariff is in each point's label.", labels=labels)


def context_chart(rows: list[dict], live: dict, first: str = "", last: str = "9999") -> dict:
    """Recorded days win; a day the ledger never recorded comes from the transcripts still on disk."""
    days: dict = {r["day"]: r["detail"]["context"] for r in rows if r["detail"].get("context")}
    for day, tools in live.items():
        days.setdefault(day, tools)
    series: dict = {}
    for day, tools in sorted(days.items()):
        for tool, n in tools.items():
            _put(series, tool, day, n)
    return _chart("Tool-result tokens into Claude's context", "tokens", fold(series),
                  "Estimated as characters / 4 per tool result (soh context).",
                  annotations=[{"day": d, "label": t} for d, t in ANNOTATIONS if first <= d <= last])


def delegation_chart(rows: list[tuple]) -> dict:
    from harness import ledger
    counts: dict = {}
    for at, lane, outcome in rows:
        c = counts.setdefault(_safe(lane), {}).setdefault(ledger.day_of(at), {"used": 0, "edited": 0,
                                                                              "discarded": 0, "pending": 0})
        c[outcome if outcome in c else "pending"] += 1
    series, labels = {}, {}
    for lane, days in counts.items():
        for day, c in days.items():
            said = c["used"] + c["edited"] + c["discarded"]
            if not said:
                continue
            series.setdefault(lane, {})[day] = round((c["used"] + c["edited"]) / said, 4)
            labels.setdefault(lane, {})[day] = (f"{c['used']} used, {c['edited']} edited, {c['discarded']} "
                                                f"discarded, {c['pending']} not recorded")
    return _chart("Delegation acceptance by lane", "rate", fold(series), "Share of recorded outcomes "
                  "that were used or edited rather than discarded.", labels=labels)


def scrub_names(charts: dict, flagged) -> dict:
    """Series the privacy scanner flags by name are summed into "other", their labels dropped."""
    for c in charts.values():
        bad = [n for n in c["series"] if n != OTHER and flagged(n)]
        for n in bad:
            for d, v in c["series"].pop(n).items():
                rest = c["series"].setdefault(OTHER, {})
                rest[d] = round(rest.get(d, 0) + v, 6)
            (c.get("labels") or {}).pop(n, None)
    return charts


def _flagged():
    from harness import privacy, publish
    pattern = publish.private_pattern()
    return lambda name: bool(privacy.scan(name, "trend", pattern))


def gather(conn, now: float, *, days: int = TREND_DAYS, limits=None, live_context=None) -> dict:
    """Every chart's daily series for this machine. Aggregates only."""
    from harness import context_report as cr, ledger
    first = _first_day(now, days)
    since = ledger.day_start(first)
    rows = ledger_rows(conn, first)
    if limits is None:
        limits = ledger.read_jsonl(ledger.ledger_dir() / "ratelimits.jsonl")
    if live_context is None:
        root = cr.default_root()
        live_context = (ledger.context_days(cr.scan(cr.transcripts(root, newer_than=since), since=since))
                        if root.is_dir() else {})
    charts = {
        "cloud": cloud_chart(rows),
        "plan_cap": plan_chart(limits, since),
        "local_tokens": local_chart(rows),
        "displaced": displaced_chart(rows),
        "energy": energy_chart(rows),
        "context": context_chart(rows, live_context, first, ledger.day_of(now)),
        "delegations": delegation_chart(delegation_rows(conn, since)),
    }
    return {"first_day": first, "last_day": ledger.day_of(now), "charts": scrub_names(charts, _flagged())}


# --- the page, on the runner -------------------------------------------------------------------

W, H = 640, 220
LEFT, RIGHT, TOP, BOTTOM = 58, 12, 22, 26


def _esc(x) -> str:
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def tick(v: float, unit: str) -> str:
    """An axis label: the unit is in the chart's title, so kWh ticks are bare numbers."""
    return f"{v:.2f}" if unit == "kwh" else fmt(v, unit)


def fmt(v: float, unit: str) -> str:
    if unit == "pct":
        return f"{v:.0f}%"
    if unit == "rate":
        return f"{v:.2f}"
    if unit == "kwh":
        return f"{v:.2f} kWh"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.0f}k"
    return f"{v:.0f}"


def _days(first: str, last: str) -> list[str]:
    a, b = _dt.date.fromisoformat(first), _dt.date.fromisoformat(last)
    return [(a + _dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _top(series: dict, unit: str) -> float:
    if unit == "pct":
        return 100.0
    if unit == "rate":
        return 1.0
    peak = max((v for s in series.values() for v in s.values()), default=0) or 1.0
    mag = 10 ** len(str(int(peak))) / 10
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if peak <= step * mag:
            return step * mag
    return peak


def svg(chart: dict) -> str:
    """One chart as inline SVG: a line per series over a day axis, a point per day with its value on hover."""
    series, unit = chart["series"], chart["unit"]
    marked = {a["day"] for a in chart.get("annotations") or []} if series else set()
    days = sorted({d for s in series.values() for d in s} | marked)
    if not days:
        return ""
    axis = _days(days[0], days[-1])
    xi = {d: i for i, d in enumerate(axis)}
    pw, ph = W - LEFT - RIGHT, H - TOP - BOTTOM
    top = _top(series, unit)
    x = (lambda d: LEFT + (pw * xi[d] / (len(axis) - 1) if len(axis) > 1 else pw / 2))
    y = (lambda v: TOP + ph - ph * min(v, top) / top)
    out = [f'<svg class="trend" viewBox="0 0 {W} {H}" role="img" aria-label="{_esc(chart["title"])}">']
    for i in range(5):
        v = top * i / 4
        out.append(f'<line class="grid" x1="{LEFT}" x2="{W - RIGHT}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="tick" x="{LEFT - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{_esc(tick(v, unit))}</text>')
    ends = {axis[0]: "start", axis[-1]: "end"} if len(axis) > 1 else {}
    for d in (axis[0], axis[len(axis) // 2], axis[-1]) if len(axis) > 2 else axis:
        out.append(f'<text class="tick" x="{x(d):.1f}" y="{H - 8}" '
                   f'text-anchor="{ends.get(d, "middle")}">{d[5:]}</text>')
    by_day: dict = {}
    for a in chart.get("annotations") or []:
        if a["day"] in xi:
            by_day.setdefault(a["day"], []).append(a["label"])
    for d, labels in by_day.items():
        xa = x(d)
        anchor = "end" if xa > LEFT + pw / 2 else "start"
        out.append(f'<line class="mark" x1="{xa:.1f}" x2="{xa:.1f}" y1="{TOP - 4}" y2="{TOP + ph}"/>'
                   f'<text class="mark-label" x="{xa + (-4 if anchor == "end" else 4):.1f}" y="{TOP - 8}" '
                   f'text-anchor="{anchor}">{_esc("; ".join(labels))}</text>')
    labels = chart.get("labels") or {}
    for n, (name, s) in enumerate(series.items()):
        colour = f"var(--s{n % MAX_SERIES + 1})"
        runs, run = [], []
        for d in axis:
            if d in s:
                run.append(d)
            elif run:
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        for r in runs:
            if len(r) > 1:
                pts = " ".join(f"{x(d):.1f},{y(s[d]):.1f}" for d in r)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for d in sorted(s):
            extra = labels.get(name, {}).get(d)
            tip = f"{name} {d}: {fmt(s[d], unit)}" + (f" ({extra})" if extra else "")
            out.append(f'<circle cx="{x(d):.1f}" cy="{y(s[d]):.1f}" r="3.5" fill="{colour}">'
                       f'<title>{_esc(tip)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def table(chart: dict) -> str:
    names = list(chart["series"])
    days = sorted({d for s in chart["series"].values() for d in s})
    head = "".join(f"<th>{_esc(n)}</th>" for n in names)
    body = "".join(
        f"<tr><td>{d}</td>" + "".join(
            f'<td class="num">{_esc(fmt(chart["series"][n][d], chart["unit"])) if d in chart["series"][n] else "--"}</td>'
            for n in names) + "</tr>" for d in days)
    return (f'<details><summary>Table</summary><div class="wide"><table><tr><th>day</th>{head}</tr>'
            f"{body}</table></div></details>")


def legend(chart: dict) -> str:
    if len(chart["series"]) < 2:
        return ""
    return '<ul class="legend">' + "".join(
        f'<li><span class="swatch" style="background:var(--s{i % MAX_SERIES + 1})"></span>{_esc(n)}</li>'
        for i, n in enumerate(chart["series"])) + "</ul>"


def figure(chart: dict) -> str:
    notes = chart.get("note") or ""
    marks = [f'{a["day"]}: {a["label"]}' for a in chart.get("annotations") or []]
    if marks:
        notes += " Marked: " + "; ".join(marks) + "."
    if not chart["series"]:
        body = '<p class="note">No data yet.</p>'
    else:
        body = svg(chart) + legend(chart) + table(chart)
    return (f'<figure class="trend-fig"><figcaption><h3>{_esc(chart["title"])}</h3></figcaption>'
            f'{body}<p class="note">{_esc(notes)}</p></figure>')


def has_data(trends: dict | None) -> bool:
    return bool(trends and any((c or {}).get("series") for c in (trends.get("charts") or {}).values()))


def render(trends: dict) -> str:
    charts = trends.get("charts") or {}
    keys = [k for k in ORDER if k in charts] + [k for k in charts if k not in ORDER]
    return (f'<p class="sub">Daily, {_esc(trends.get("first_day"))} to {_esc(trends.get("last_day"))}. '
            f'Hover a point for its value; each chart has a table.</p>'
            + "".join(figure(charts[k]) for k in keys))


CSS = """
:root { --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100;
        --s5:#e87ba4; --s6:#008300; --s7:#6250d6; --s8:#e34948; }
@media (prefers-color-scheme: dark) {
  :root { --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500;
          --s5:#d55181; --s6:#008300; --s7:#9085e9; --s8:#e66767; } }
svg.trend { width:100%; height:auto; display:block; }
svg.trend .grid { stroke:var(--dim); stroke-opacity:.25; stroke-width:1; }
svg.trend .tick { fill:var(--dim); font:11px 'IBM Plex Mono',monospace; }
svg.trend .mark { stroke:var(--ink); stroke-dasharray:4 3; stroke-width:1; }
svg.trend .mark-label { fill:var(--ink); font:11px 'IBM Plex Sans',sans-serif; }
svg.trend circle { stroke:var(--sand); stroke-width:2; }
.trend-fig { margin:0 0 18px; }
ul.legend { list-style:none; padding:0; margin:6px 0; display:flex; flex-wrap:wrap; gap:4px 14px; }
ul.legend li { display:flex; align-items:center; gap:6px; font-size:13px; }
.swatch { width:12px; height:12px; border-radius:3px; display:inline-block; }
"""
