"""The status page drawn as tiles, a ratio gauge, a 24 h timeline and a monitor dot grid (#2078)."""
from __future__ import annotations

import html
import math
import re
import time
from datetime import date

OK, WARN, BAD, UNKNOWN = "ok", "warn", "bad", "unknown"
ICON = {OK: "✓", WARN: "!", BAD: "✕", UNKNOWN: "?"}
WORD = {OK: "OK", WARN: "attention", BAD: "failing", UNKNOWN: "unknown"}
#: Seconds after the last daily dump before the Store tile turns amber; a day's slip is not news. #2078.
BACKUP_STALE_S = 2 * 86400.0
_HOME = re.compile(r"/(?:Users|home)/[^/\s'\"<>]+")
_SHA = re.compile(r"\b([0-9a-f]{8})[0-9a-f]{4,32}\b")
_GAUGE = (-2.0, 1.0)
_LANES = (("deploy", "Deploys"), ("discovery", "Discovery"), ("job", "Jobs"), ("alert", "Alerts"), ("pause", "Pauses"))


def short(text) -> str:
    """Home paths as ~ and shas cut to 8 characters."""
    return _SHA.sub(r"\1", _HOME.sub("~", str(text)))


def esc(text) -> str:
    return html.escape(short(text), quote=True)


def tok(n) -> str:
    if n is None:
        return "n/a"
    for div, unit in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= div:
            v = n / div
            return f"{v:.1f}{unit}" if v < 10 else f"{v:.0f}{unit}"
    return f"{n:.0f}"


def span(s: float) -> str:
    if s < 3600:
        return f"{max(1, round(s / 60))} min"
    return f"{s / 3600:.0f} h" if s < 172800 else f"{s / 86400:.0f} d"


def ago(t, now: float) -> str:
    if not t:
        return "never"
    s = now - float(t)
    return "just now" if s < 60 else span(s) + " ago"


def stamp(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(t))) if t else ""


def hm(t) -> str:
    return time.strftime("%H:%M", time.localtime(float(t))) if t else "?"


def ratio_text(r) -> str:
    if r is None:
        return "n/a"
    if r >= 1:
        return f"{r:.0f}:1" if abs(r - round(r)) < 0.05 else f"{r:.1f}:1"
    return f"1:{1 / r:.0f}"


def _deploy(d: dict, now: float):
    last = d.get("last") or {}
    if d.get("error"):
        return UNKNOWN, "not read", None
    if d.get("failing"):
        return BAD, f"{d['failing']} failed · last {ago(last.get('at'), now)}", last.get("at")
    if d.get("wait"):
        return WARN, f"release waiting {span(d['wait'].get('waited') or 0)}", d["wait"].get("since")
    if not last:
        return UNKNOWN, "history not read" if d.get("why") else "no deploy in 7 days", None
    if d.get("behind"):
        return WARN, f"{d['behind']} commits behind main", last.get("at")
    return OK, f"release {last['id']} · {ago(last.get('at'), now)}", last.get("at")


def _queue(q: dict, now: float):
    from harness import queue_stale
    if q.get("error"):
        return UNKNOWN, "not read", None
    since = q.get("paused_since")
    if q.get("paused"):
        if not since:
            return WARN, "paused", None
        return (BAD if now - since > queue_stale.QUEUE_STALE_S else WARN), f"paused {span(now - since)}", since
    if q.get("why"):
        return UNKNOWN, "jobs not read", None
    run, moved = q.get("running") or [], q.get("last_moved")
    if run:
        return OK, f"running {run[0].get('kind')} · {q.get('pending') or 0} pending", moved
    if q.get("pending"):
        return OK, f"{q['pending']} pending · moved {ago(moved, now)}", moved
    return OK, f"idle · last job {ago(moved, now)}", moved


def _discovery(disc: dict, now: float):
    from harness.status_page import discovery_failed
    if disc.get("error"):
        return UNKNOWN, "not read", None
    nxt = f" · next {hm(disc['next'])}" if disc.get("next") else ""
    st = disc.get("status")
    if st == "stalled":
        return BAD, "stalled" + nxt, disc.get("started")
    if discovery_failed(disc):
        return BAD, f"failed {ago(disc.get('finished'), now)}{nxt}", disc.get("finished")
    if disc.get("overdue"):
        return WARN, "overdue" + nxt, disc.get("finished")
    if not st:
        return UNKNOWN, "no heartbeat" + nxt, None
    if st == "finished":
        return OK, f"ran {ago(disc.get('finished'), now)}{nxt}", disc.get("finished")
    return OK, f"{st} · since {ago(disc.get('started'), now).removesuffix(' ago')}", disc.get("started")


def _monitor(mon: dict, now: float):
    if mon.get("error"):
        return UNKNOWN, "not read", None
    checks = mon.get("checks") or []
    bad = [c for c in checks if not c["ok"]]
    if not mon.get("running"):
        return BAD, "monit not running", None
    if bad:
        return BAD, f"{len(bad)} of {len(checks)} checks failing", None
    if not checks:
        return UNKNOWN, "no checks read", None
    head = f"{len(checks)}/{len(checks)} checks OK"
    if not mon.get("current"):
        return WARN, head + " · config stale", None
    if not mon.get("alerting"):
        return WARN, head + " · desktop alerts only", None
    return OK, head, mon.get("last_alert_at")


def _services(sv: dict, now: float):
    if sv.get("error"):
        return UNKNOWN, "not read", None
    nodes, lane = sv.get("nodes") or [], sv.get("lane") or {}
    down = [n for n in nodes if n.get("down_now")]
    if lane.get("generating") is False:
        return BAD, f"{lane.get('lane')} lane cannot generate", None
    if down:
        return BAD, f"{len(down)} of {len(nodes)} nodes down", None
    up = f"{len(nodes)} node{'' if len(nodes) == 1 else 's'} up"
    if lane.get("generating") is None:
        return (OK if nodes else UNKNOWN), up + " · lane unchecked", None
    return OK, up + " · lane generating", None


def _store(s: dict, now: float):
    if not s.get("up"):
        return BAD, "store down", None
    if s.get("error"):
        return UNKNOWN, "not read", None
    b = s.get("backup_at")
    head = f"schema {s.get('schema')} · backup {ago(b, now)}"
    return (WARN if not b or now - b > BACKUP_STALE_S else OK), head, b


TILES = (("Deploy", "deploy", _deploy), ("Queue", "queue", _queue), ("Discovery", "discovery", _discovery),
         ("Monitor", "monitor", _monitor), ("Services", "services", _services), ("Store", "store", _store))


def tiles(r: dict, now: float) -> list[dict]:
    """Each tile's state, headline and the time its headline is about."""
    out = []
    for name, key, fn in TILES:
        state, head, at = fn(r[key], now)
        out.append({"name": name, "key": key, "state": state, "headline": head, "at": at})
    return out


def alerts(r: dict) -> list[dict]:
    """Each banner line as a short title and the detail that belongs under it."""
    out = []
    for b in r.get("banner") or []:
        title, _, detail = b.partition(": ")
        out.append({"title": title[:1].upper() + title[1:], "detail": detail})
    return out


def _badge(state: str) -> str:
    return f"<b class='badge {state}' role='img' aria-label='{WORD[state]}'>{ICON[state]}</b>"


def _when(t, now: float, text: str | None = None) -> str:
    return f"<time title='{stamp(t)}'>{esc(text or ago(t, now))}</time>" if t else esc(text or "never")


def _tile(t: dict, body: list[str], as_of, now: float) -> str:
    head = esc(t["headline"])
    if t["at"]:
        head = f"<span title='{stamp(t['at'])}'>{head}</span>"
    return (f"<details class='tile {t['state']}' data-tile='{t['key']}'><summary>{_badge(t['state'])}"
            f"<h2>{esc(t['name'])} <span class='asof'>as of {_when(as_of, now)}</span></h2>"
            f"<p class='head'>{head}</p></summary><ul>{''.join(f'<li>{esc(x)}</li>' for x in body)}</ul></details>")


def _pos(r: float) -> float:
    lo, hi = _GAUGE
    return max(0.0, min(100.0, (math.log10(r) - lo) / (hi - lo) * 100)) if r and r > 0 else 0.0


def _gauge(h: dict) -> str:
    week, yday = h["week"], h["yesterday"]
    target = week.get("target") or 3.0
    marks = [f"<span class='zone' style='left:{_pos(target):.1f}%'></span>",
             f"<span class='tgt' style='left:{_pos(target):.1f}%'></span>",
             f"<span class='tgtl' style='left:{_pos(target):.1f}%'>target</span>"]
    if yday.get("ratio"):
        marks.append(f"<span class='mk hollow' style='left:{_pos(yday['ratio']):.1f}%' "
                     f"title='{esc(yday['last_day'])} {ratio_text(yday['ratio'])}'></span>")
    if week.get("ratio"):
        marks.append(f"<span class='mk' style='left:{_pos(week['ratio']):.1f}%' "
                     f"title='{week['days']} days {ratio_text(week['ratio'])}'></span>")
    ticks = "".join(f"<span style='left:{_pos(10 ** e):.1f}%'>{ratio_text(10 ** e)}</span>" for e in (-2, -1, 0, 1))
    label = (f"local to cloud tokens on a log scale: {week['days']} days {ratio_text(week.get('ratio'))}, "
             f"yesterday {ratio_text(yday.get('ratio'))}, target {ratio_text(target)}")
    short_by = f" · {target / week['ratio']:.0f}× short" if week.get("ratio") and week["ratio"] < target else ""
    return (f"<div class='gauge' role='img' aria-label='{esc(label)}'><div class='track'>{''.join(marks)}</div>"
            f"<div class='ticks'>{ticks}</div></div>"
            f"<p class='key'><span class='kmk'></span> {week['days']} days {ratio_text(week.get('ratio'))} "
            f"<span class='kmk hollow'></span> yesterday {ratio_text(yday.get('ratio'))} "
            f"<span class='ktgt'></span> target {ratio_text(target)}{short_by}</p>")


def _bars(days: list[dict]) -> str:
    out = ["<div class='bars'>"]
    for key, name, color in (("local", "local", "var(--c1)"), ("cloud", "cloud", "var(--c2)")):
        vals = [d.get(key) for d in days]
        top = max([v for v in vals if v] or [1])
        cols = []
        for d, v in zip(days, vals):
            if v is None:
                cols.append(f"<span class='col none' title='{esc(d['day'])} {name}: no count'></span>")
            else:
                cols.append(f"<span class='col' title='{esc(d['day'])} {name} {tok(v)}'>"
                            f"<i style='height:{max(2.0, v / top * 100):.1f}%;background:{color}'></i></span>")
        total = sum(v for v in vals if v)
        out.append(f"<div class='brow'><span class='bl'><i class='sw' style='background:{color}'></i>{name}"
                   f" <b>{tok(total)}</b></span><span class='cols'>{''.join(cols)}</span></div>")
    labels = "".join(f"<span>{date.fromisoformat(d['day']).strftime('%a')}</span>" for d in days)
    out.append(f"<div class='brow'><span class='bl'></span><span class='cols dl'>{labels}</span></div></div>")
    return "".join(out)


def _causes(causes: list[dict], counted) -> str:
    if not causes or not counted:
        return ""
    colors = ["var(--c3)", "var(--c4)", "var(--c5)"]
    segs, keys = [], []
    for i, c in enumerate(causes):
        color = "var(--other)" if c["term"] == "other" else colors[min(i, len(colors) - 1)]
        share = c["tokens"] / counted
        segs.append(f"<span style='width:{share * 100:.1f}%;background:{color}' "
                    f"title='{esc(c['term'])} {tok(c['tokens'])} ({share:.0%})'></span>")
        keys.append(f"<li><i class='sw' style='background:{color}'></i>{esc(c['term'])} · {tok(c['tokens'])} · {share:.0%}</li>")
    big = max(causes, key=lambda c: c["tokens"])
    return (f"<h3>Cloud {tok(counted)} by cause</h3><p class='big'>largest: <b>{esc(big['term'])}</b> "
            f"{big['tokens'] / counted:.0%}</p><div class='stack'>{''.join(segs)}</div><ul class='keys'>{''.join(keys)}</ul>")


def _ratio(ra: dict, body: list[str], now: float) -> str:
    h = ra.get("headline")
    out = [f"<section class='panel'><h2>Ratio <span class='asof'>as of {_when(ra.get('as_of'), now)}</span></h2>"]
    if h and h["week"].get("ratio") is not None:
        out.append(f"<p class='hero'>{ratio_text(h['week']['ratio'])} <span>local:cloud, {h['week']['days']} days</span></p>")
        out.append(_gauge(h))
    else:
        out.append(f"<p class='head'>{_badge(UNKNOWN)} ratio not read</p>")
    if ra.get("days"):
        out.append("<h3>Tokens per day <span class='asof'>each row on its own scale</span></h3>" + _bars(ra["days"]))
    out.append(_causes(ra.get("causes") or [], ra.get("counted")))
    out.append(f"<details><summary>detail</summary><ul>{''.join(f'<li>{esc(x)}</li>' for x in body)}</ul></details>")
    return "".join(out) + "</section>"


def _timeline(tl: dict, now: float) -> str:
    out = [f"<section class='panel'><h2>Last 24 h <span class='asof'>as of {_when(tl.get('as_of'), now)}</span></h2>"]
    if tl.get("error"):
        return "".join(out) + f"<p class='head'>{_badge(UNKNOWN)} not read</p></section>"
    lo, hi = tl["since"], tl["until"]
    pct = lambda t: max(0.0, min(100.0, (float(t) - lo) / (hi - lo) * 100))  # noqa: E731
    out.append("<div class='tl'>")
    for kind, name in _LANES:
        marks = []
        for e in [e for e in tl.get("events") or [] if e["kind"] == kind]:
            tip = esc(f"{e['label']} · {stamp(e['at'])}")
            if e.get("end"):
                marks.append(f"<span class='bar {e['state']}' style='left:{pct(e['at']):.2f}%;"
                             f"width:{max(0.6, pct(e['end']) - pct(e['at'])):.2f}%' title='{tip}'></span>")
            marks.append(f"<span class='ev {e['state']}' style='left:{pct(e['at']):.2f}%' title='{tip}' "
                         f"aria-label='{tip}'>{ICON[e['state']]}</span>")
        out.append(f"<div class='lane'><span class='ln'>{name}</span><span class='lt'>{''.join(marks)}</span></div>")
    ticks = "".join(f"<span style='left:{i * 25}%'>{'now' if i == 4 else hm(lo + i * (hi - lo) / 4)}</span>" for i in range(5))
    out.append(f"<div class='lane'><span class='ln'></span><span class='lt ax'>{ticks}</span></div></div>")
    return "".join(out) + "</section>"


def _checks(mon: dict) -> str:
    checks = mon.get("checks") or []
    if not checks:
        return ""
    dots = "".join(f"<span class='chk' title='{esc(c['type'])}: {esc(c['state'])}'>{_badge(OK if c['ok'] else BAD)}"
                   f"{esc(c['check'])}</span>" for c in checks)
    return f"<section class='panel'><h2>Monitor checks</h2><div class='dots'>{dots}</div></section>"


_DARK = ("--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--grid:#2c2c2a;--axis:#383835;"
         "--ring:rgba(255,255,255,.12);--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--other:#5a5955")
CSS = (":root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e1e0d9;--axis:#c3c2b7;"
       "--ring:rgba(11,11,11,.12);--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--other:#b5b4ad;"
       "--good:#0ca30c;--warn:#fab219;--bad:#d03b3b;--unk:#898781}"
       f"@media (prefers-color-scheme: dark){{:root:not([data-theme=light]){{{_DARK}}}}}:root[data-theme=dark]{{{_DARK}}}"
       """
*{box-sizing:border-box}
body{background:var(--page);color:var(--ink);font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif;margin:0 auto;max-width:980px;padding:16px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:0}h3{font-size:13px;margin:14px 0 6px;color:var(--ink2)}
.asof{color:var(--ink2);font-weight:normal;font-size:12px}a{color:var(--c1)}
.top{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;margin-bottom:10px}
.clear{margin:8px 0 14px;font-weight:600;display:flex;gap:8px;align-items:center}
.alert{background:var(--surface);border:1px solid var(--ring);border-left:4px solid var(--bad);border-radius:6px;padding:8px 10px;margin:0 0 8px}
.alert summary{font-weight:600}.alert p{margin:6px 0 0;color:var(--ink2);overflow-wrap:anywhere;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:0 0 14px;align-items:start}
.tile,.panel{background:var(--surface);border:1px solid var(--ring);border-radius:8px}
.tile{border-left:4px solid var(--st);padding:10px}.tile summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto 1fr;gap:2px 8px}
.tile summary::-webkit-details-marker{display:none}.tile h2{align-self:center}.tile .head{grid-column:1/-1;margin:4px 0 0;font-weight:600}
.tile ul,.panel details ul{margin:8px 0 0;padding-left:18px;font-size:13px;color:var(--ink2)}li{overflow-wrap:anywhere}
.tile[open]{grid-column:1/-1}.tile h2 .asof{display:block;margin-top:2px}
@media (min-width:700px){.tiles{grid-template-columns:repeat(3,minmax(0,1fr))}}
.ok{--st:var(--good)}.warn{--st:var(--warn)}.bad{--st:var(--bad)}.unknown{--st:var(--unk)}
.badge{display:inline-grid;place-items:center;width:20px;height:20px;border-radius:50%;background:var(--st);color:#fff;font-size:12px;flex:none}
.badge.warn,.badge.unknown{color:#0b0b0b}
.panel{padding:12px;margin:0 0 14px}.panel summary{cursor:pointer;color:var(--ink2);font-size:13px;margin-top:10px}
.hero{font-size:28px;font-weight:700;margin:6px 0}.hero span{font-size:13px;font-weight:normal;color:var(--ink2)}
.gauge{margin:18px 4px 4px}.track{position:relative;height:10px;background:var(--grid);border-radius:5px}
.zone{position:absolute;top:0;bottom:0;right:0;background:var(--good);opacity:.35;border-radius:0 5px 5px 0}
.tgt{position:absolute;top:-5px;bottom:-5px;width:2px;background:var(--ink);transform:translateX(-1px)}
.tgtl{position:absolute;top:-20px;font-size:11px;color:var(--ink2);transform:translateX(-50%)}
.mk{position:absolute;top:50%;width:14px;height:14px;border-radius:50%;background:var(--c1);border:2px solid var(--surface);transform:translate(-50%,-50%)}
.mk.hollow{background:var(--surface);border:2px solid var(--c1);width:12px;height:12px}
.ticks{position:relative;height:16px;margin-top:4px;font-size:11px;color:var(--ink2)}
.ticks span,.ax span{position:absolute;transform:translateX(-50%);white-space:nowrap}
.ticks span:first-child,.ax span:first-child{transform:none}.ticks span:last-child,.ax span:last-child{transform:translateX(-100%)}
.key{font-size:13px;color:var(--ink2);margin:6px 0 0}
.kmk,.ktgt{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--c1);vertical-align:-1px;margin-left:6px}
.kmk.hollow{background:none;border:2px solid var(--c1)}.ktgt{width:2px;border-radius:0;height:12px;background:var(--ink)}
.bars{font-size:12px}.brow{display:flex;align-items:flex-end;gap:8px;margin-bottom:4px}
.bl{flex:0 0 92px;color:var(--ink2)}.bl b{color:var(--ink)}
.cols{flex:1;display:flex;gap:2px;height:48px;align-items:flex-end;border-bottom:1px solid var(--axis)}
.cols.dl{height:auto;border:0;color:var(--ink2)}.cols.dl span{flex:1;text-align:center}
.col{flex:1;height:100%;display:flex;align-items:flex-end}.col i{display:block;width:100%;border-radius:4px 4px 0 0}
.col.none{background:repeating-linear-gradient(45deg,transparent 0 4px,var(--grid) 4px 6px)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.big{margin:0 0 6px;font-size:13px}.stack{display:flex;gap:2px;height:16px}.stack span{min-width:2px;border-radius:2px}
.keys{list-style:none;padding:0;margin:6px 0 0;font-size:12px;color:var(--ink2)}.keys li{margin:2px 0}
.tl{font-size:12px}.lane{display:flex;align-items:center;gap:8px;height:24px}.ln{flex:0 0 70px;color:var(--ink2)}
.lt{flex:1;position:relative;height:100%;border-bottom:1px solid var(--grid)}.lt.ax{border:0;color:var(--ink2)}
.ev{position:absolute;top:50%;transform:translate(-50%,-50%);width:16px;height:16px;border-radius:50%;background:var(--st);color:#fff;font-size:10px;display:grid;place-items:center;border:2px solid var(--surface)}
.ev.warn,.ev.unknown{color:#0b0b0b}
.bar{position:absolute;top:50%;height:6px;transform:translateY(-50%);background:var(--st);opacity:.45;border-radius:3px}
.dots{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px 12px;font-size:13px}
.chk{display:flex;gap:6px;align-items:center;overflow-wrap:anywhere}.chk .badge{width:16px;height:16px;font-size:10px}
""")


def page(r: dict, lines: dict[str, list[str]], now: float | None = None) -> str:
    """The page: banner or all clear, six tiles, the ratio panel, the 24 h strip and the monitor grid."""
    now = time.time() if now is None else now
    gen = r["generated"]
    out = ["<!doctype html><html><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           f"<meta http-equiv='refresh' content='{int(r.get('refresh_s') or 60)}'>",
           f"<title>SoHoT status</title><style>{CSS}</style></head><body>",
           f"<div class='top'><h1>SoHoT status</h1><span class='asof'>gathered {_when(gen, now)} · "
           "<a href='status.json'>json</a></span></div>"]
    got = alerts(r)
    if got:
        out.append("<div class='banner'>")
        for a in got:
            if a["detail"]:
                out.append(f"<details class='alert'><summary>{_badge(BAD)} {esc(a['title'])}</summary>"
                           f"<p>{esc(a['detail'])}</p></details>")
            else:
                out.append(f"<div class='alert'><b>{_badge(BAD)} {esc(a['title'])}</b></div>")
        out.append("</div>")
    else:
        out.append(f"<p class='clear'>{_badge(OK)} All clear. Nothing needs you.</p>")
    out.append("<div class='tiles'>")
    out += [_tile(t, lines.get(t["name"]) or [], r[t["key"]].get("as_of"), now) for t in tiles(r, now)]
    out.append("</div>")
    out.append(_ratio(r["ratio"], lines.get("Ratio") or [], now))
    out.append(_timeline(r.get("timeline") or {"error": "not gathered"}, now))
    out.append(_checks(r["monitor"]))
    out.append("</body></html>")
    return "\n".join(out)
