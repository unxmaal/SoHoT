"""One page showing where the harness stands. Issue #231.

Answering "how have our lanes changed recently" took six commands and ad-hoc
SQL, and the answer landed in a chat message that was stale immediately. Every
fact is already in the store and the receipts; nothing assembled them.

`state()` gathers. `render()` writes a self-contained HTML file: no server, no
build step, no network, openable from disk on the machine this runs on.

THE TWO THINGS THAT NEED SAYING ABOUT DESIGN:

  * "CHANGED" NEEDS A REFERENT. A page cannot highlight what changed without a
    previous state to compare against, so each run writes its state beside the
    page and the next run diffs it. Without that, "changed lanes" silently
    means "lanes", every time.
  * STALENESS IS THREE DIFFERENT THINGS and collapsing them hides the worst.
    A source not fetched lately is a fetch problem; a lane with no receipt AT
    ALL is not stale, it is unverified, and saying "42 days" for it would be
    a fabrication.
"""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

#: A lane measured longer ago than this is called out. Not a hard rule: it is
#: the same interval the sources use, because a lane older than the discovery
#: cycle has had candidates proposed against it that it never answered.
STALE_LANE_DAYS = 7.0

#: The ladder in the order work flows through it. NOT memory_store.TIERS,
#: which enumerates valid tier NAMES and omits `fetch` because nothing
#: validates a fetch verdict against it. Two different questions.
LADDER = ("inspect", "judge", "fetch", "screen", "measure", "adopt")


def _load_state(path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def funnel(conn) -> list[dict]:
    """Candidates and verdicts per tier, cheapest tier first.

    The honest measure of whether the loop is turning: a wide top and an empty
    bottom is a queue rather than a loop.
    """
    order = {t: i for i, t in enumerate(LADDER)}
    rows = conn.execute(
        "SELECT tier, COUNT(DISTINCT proposal_id) AS candidates, "
        "COUNT(*) AS verdicts FROM verdicts GROUP BY tier").fetchall()
    out = [dict(r) for r in rows]
    return sorted(out, key=lambda r: order.get(r["tier"], 99))


def lanes_state(conn) -> list[dict]:
    """Per lane: what it serves, its own stored row, and what won.

    The numbers are the SERVED candidate's row, by candidate id, from the
    newest stored measure run on this machine that ran it (#410, #341). What
    won is beaten_in(), reported beside it, never in its place.
    """
    from harness import adopt, lanes as L, runs, winners

    typed = winners.typed()
    measured = winners.beaten_in(conn)
    adopted = adopt.current(conn)
    mine = runs.here(conn)
    now = time.time()
    out = []
    for lane in L.ALL:
        got = measured.get(lane) or {}
        held = adopted.get(lane) or {}
        serves = held.get("spec") or typed.get(lane, "")
        cid = held.get("candidate_id") or _candidate_of(conn, lane, serves)
        # Last measured: any measure run of the lane; the row: the served one. #234.
        newest = runs.newest(conn, lane=lane, machines=mine, tier=runs.MEASURE)
        ran = runs.newest(conn, lane=lane, machines=mine,
                          tier=runs.MEASURE, candidate_id=cid) if cid else None
        here = runs.row_for(conn, ran["id"], cid) if ran else {}
        age = runs.age_days(newest, now)
        out.append({
            "lane": lane,
            "wanted": lane in L.WANTED,
            "serves": serves,
            "adopted": bool(held),
            "adopted_how": held.get("how", ""),
            "candidate_id": cid,
            "measured": here.get("candidate") or "",
            "pass_rate": here.get("pass_rate"),
            "median_s": here.get("median_s"),
            "ttft_median_s": here.get("ttft_median_s"),
            "ttft_p95_s": here.get("ttft_p95_s"),
            "metrics": here.get("metrics") or {},
            "run": ran["path"] if ran else "",
            "best": got.get("candidate", ""),
            "best_pass_rate": got.get("pass_rate"),
            "best_median_s": got.get("median_s"),
            "best_run": got.get("run", ""),
            "last_run": newest["path"] if newest else "",
            "age_days": age,
            # Unverified: nothing ran here. Parked: somebody decided. #244.
            "unverified": not newest and not L.parked(lane)[0],
            "parked": L.parked(lane)[0],
            "parked_until": L.parked(lane)[1],
            "stale": bool(age is not None and age > STALE_LANE_DAYS
                          and not L.parked(lane)[0]),
        })
    return out


def _candidate_of(conn, lane: str, serves: str) -> int | None:
    """The candidates row of what a lane serves."""
    from harness import candidates, screen
    if not serves:
        return None
    spec = screen.candidate_for(lane, serves) or serves
    return candidates.ensure(conn, spec, lane=lane)


def queue_state(conn) -> dict:
    from harness import rank, lanes as L

    rows = ms_judgeable(conn)
    ranked = rank.rank(rows, serving=rank.serving(),
                       measured_lanes=rank.lanes_with_receipts(conn))
    per_lane = {}
    for r in ranked:
        per_lane.setdefault(rank.lane_of(r), []).append(r)
    return {
        "waiting": len(rows),
        "rankable": len(ranked),
        "by_lane": {lane: len(v) for lane, v in sorted(per_lane.items())},
        "top": [{"name": r["name"], "value": r["value"],
                 "lane": rank.lane_of(r), "why": r["value_why"]}
                for r in ranked[:10]],
        "wanted_with_none": [lane for lane in L.WANTED
                             if not per_lane.get(lane)],
    }


def ms_judgeable(conn):
    from harness import memory_store as ms
    return ms.judgeable(conn, limit=1_000_000)


def machine_state() -> dict:
    from harness import machine

    m = machine.detect()
    acc = m.accelerator
    return {
        "runtimes": sorted(m.runtimes),
        "accelerator": getattr(acc, "name", ""),
        "kind": getattr(acc, "kind", ""),
        "total_gb": getattr(acc, "total_gb", 0.0),
        "available_gb": getattr(acc, "available_gb", 0.0),
    }


def state(conn=None) -> dict:
    """Everything the page shows, as plain data."""
    from harness import feeds
    from harness import memory_store as ms

    close = conn is None
    conn = conn or ms.connect()
    try:
        return {
            "generated": time.time(),
            "machine": machine_state(),
            "funnel": funnel(conn),
            "lanes": lanes_state(conn),
            "queue": queue_state(conn),
            "sources": feeds.staleness(store=conn),
        }
    finally:
        if close:
            conn.close()


def changes(now: dict, before: dict) -> dict:
    """What moved since the last report, keyed by lane.

    Empty when there is no previous state, which is the honest answer on a
    first run and must not render as "nothing changed".
    """
    if not before:
        return {}
    was = {l["lane"]: l for l in before.get("lanes") or []}
    out = {}
    for lane in now.get("lanes") or []:
        old = was.get(lane["lane"])
        if not old:
            out[lane["lane"]] = "new lane"
            continue
        if old.get("serves") != lane.get("serves"):
            out[lane["lane"]] = (f"serves {lane['serves'] or 'nothing'}, "
                                 f"was {old.get('serves') or 'nothing'}")
        elif old.get("run") != lane.get("run") and lane.get("run"):
            out[lane["lane"]] = f"re-measured in {lane['run']}"
    return out


CSS = """
:root { --fg:#1a1a1a; --dim:#6a6a6a; --line:#dcdcdc; --bg:#fff;
        --warn:#8a5a00; --warnbg:#fff6e0; --bad:#8a1f1f; --badbg:#fdeaea;
        --good:#14532d; --goodbg:#e8f5ec; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e6e6e6; --dim:#9a9a9a; --line:#333; --bg:#151515;
          --warn:#ffca6a; --warnbg:#2e2408; --bad:#ff9b9b; --badbg:#2e1212;
          --good:#8ee7ab; --goodbg:#0f2a19; } }
* { box-sizing:border-box }
body { margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
       font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
main { max-width:60rem; margin:0 auto }
h1 { font-size:1.15rem; margin:0 0 .25rem }
h2 { font-size:.95rem; margin:2.25rem 0 .5rem; padding-bottom:.25rem;
     border-bottom:1px solid var(--line) }
.sub { color:var(--dim); margin:0 0 .25rem }
table { border-collapse:collapse; width:100%; margin:.5rem 0 }
th,td { text-align:left; padding:.3rem .55rem; border-bottom:1px solid var(--line);
        vertical-align:top }
th { color:var(--dim); font-weight:600; white-space:nowrap }
td.num { text-align:right; font-variant-numeric:tabular-nums }
.tag { display:inline-block; padding:0 .4rem; border-radius:3px; font-size:.8rem;
       white-space:nowrap }
.warn { background:var(--warnbg); color:var(--warn) }
.bad  { background:var(--badbg);  color:var(--bad) }
.good { background:var(--goodbg); color:var(--good) }
tr.changed td { background:var(--goodbg) }
.dim { color:var(--dim) }
.note { color:var(--dim); margin:.4rem 0 0; font-size:.85rem }
.bar { display:inline-block; height:.6rem; background:currentColor; opacity:.35;
       vertical-align:middle; margin-left:.5rem }
"""


def _esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _days(n) -> str:
    if n is None:
        return "--"
    return f"{n:.1f}d" if n < 10 else f"{n:.0f}d"


def ttft_text(median, p95) -> str:
    """Warm time to first token as `median / p95`, or -- where unmeasured. #468."""
    if median is None:
        return "--"
    return f"{median:.2f}s / {p95:.2f}s" if p95 is not None else f"{median:.2f}s"


def _lane_rows(lanes, changed) -> str:
    out = []
    for l in lanes:
        why = changed.get(l["lane"], "")
        tags = []
        if l["adopted"]:
            tags.append('<span class="tag good">adopted</span>')
        if l["unverified"]:
            tags.append('<span class="tag bad">no receipt here</span>')
        elif l["stale"]:
            tags.append(f'<span class="tag warn">last run '
                        f'{_days(l["age_days"])} ago</span>')
        metric = " ".join(f"{k} {v:.3f}" for k, v in
                          sorted((l["metrics"] or {}).items()))[:44]
        rate = ("--" if l["pass_rate"] is None
                else f"{l['pass_rate']:.2f}")
        med = "--" if l["median_s"] is None else f"{l['median_s']:.2f}s"
        ttft = ttft_text(l.get("ttft_median_s"), l.get("ttft_p95_s"))
        out.append(
            f'<tr class="{"changed" if why else ""}">'
            f'<td>{_esc(l["lane"])}'
            f'{"" if l["wanted"] else " <span class=dim>(not on the wanted list)</span>"}</td>'
            f'<td>{_esc(l["serves"]) or "<span class=dim>--</span>"}</td>'
            f'<td class="num">{rate}</td><td class="num">{med}</td>'
            f'<td class="num">{ttft}</td>'
            f'<td class="dim">{_esc(metric)}</td>'
            f'<td>{" ".join(tags)}{" " if tags and why else ""}'
            f'{f"<span class=tag good>{_esc(why)}</span>" if why else ""}</td>'
            f'</tr>')
    return "\n".join(out)


def _funnel_rows(rows) -> str:
    top = max([r["candidates"] for r in rows] or [1])
    out = []
    for r in rows:
        width = max(1, round(18 * r["candidates"] / top))
        out.append(
            f'<tr><td>{_esc(r["tier"])}</td>'
            f'<td class="num">{r["candidates"]}'
            f'<span class="bar" style="width:{width}ch"></span></td>'
            f'<td class="num dim">{r["verdicts"]}</td></tr>')
    return "\n".join(out)


def _source_rows(rows) -> str:
    out = []
    for s in rows:
        tag = ('<span class="tag warn">stale</span>' if s.get("stale")
               else '<span class="tag good">ok</span>')
        age = ("never" if not s.get("last_fetched")
               else _days(s.get("age_days")))
        out.append(f'<tr><td>{_esc(s["name"])}</td>'
                   f'<td class="num">{age}</td><td>{tag}</td></tr>')
    return "\n".join(out)


def render(now: dict, before: dict | None = None) -> str:
    """The page, whole and self-contained."""
    changed = changes(now, before or {})
    q = now["queue"]
    m = now["machine"]
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(now["generated"]))
    empty = ", ".join(q["wanted_with_none"])
    first_run = "" if before else (
        '<p class="note">No previous report to compare against, so nothing is '
        'marked changed. That is different from nothing having changed.</p>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SoHoT</title><style>{CSS}</style></head>
<body><main>
<h1>SoHoT</h1>
<p class="sub">{_esc(when)} &middot; {_esc(', '.join(m['runtimes']))}
 &middot; {_esc(m['kind'])} {m['total_gb']:.0f} GB</p>

<h2>Lanes</h2>
<table><tr><th>lane</th><th>serves</th><th>pass</th><th>median</th>
<th>TTFT med / p95</th><th>metric</th><th></th></tr>
{_lane_rows(now['lanes'], changed)}
</table>
{first_run}
<p class="note">TTFT is request to first answer token on warm rows only, a
fact beside latency that no lane adopts on. Through claude -p it includes the
CLI start and the network.</p>
<p class="note">Wall-clock is only comparable with runs taken on an equally
quiet machine, and never across accelerators or serving engines. A lane with
no receipt here is unverified rather than stale: there is no age to quote.</p>

<h2>The ladder</h2>
<table><tr><th>tier</th><th>candidates</th><th>verdicts</th></tr>
{_funnel_rows(now['funnel'])}
</table>
<p class="note">A wide top and an empty bottom is a queue, not a loop.</p>

<h2>Queue</h2>
<p class="sub">{q['rankable']} rankable of {q['waiting']} waiting
{f"&middot; nothing queued for {_esc(empty)}" if empty else ""}</p>
<table><tr><th>candidate</th><th>lane</th><th>value</th><th>why</th></tr>
{"".join(f'<tr><td>{_esc(t["name"])}</td><td>{_esc(t["lane"])}</td>'
         f'<td class="num">{t["value"]:+.1f}</td>'
         f'<td class="dim">{_esc(t["why"])}</td></tr>' for t in q["top"])}
</table>

<h2>Sources</h2>
<table><tr><th>source</th><th>last read</th><th></th></tr>
{_source_rows(now['sources'])}
</table>
</main></body></html>
"""


def write(out=None, conn=None) -> Path:
    """Write the page and the state it was built from. Returns the page.

    The state sits beside the page because the NEXT run needs it: without a
    previous state, "changed" has no referent.
    """
    from harness import paths

    out = Path(out) if out else paths.home() / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    before = _load_state(out.with_suffix(".json"))
    now = state(conn)
    out.write_text(render(now, before), encoding="utf-8")
    out.with_suffix(".json").write_text(
        json.dumps(now, indent=1, default=str), encoding="utf-8")
    return out
