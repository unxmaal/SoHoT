"""The public site: a front page, the lane report and the benchmarks, all from the exports. #561.

Every number on the front page is computed here from the machine exports and
printed beside the machine and date it came from.
"""
from __future__ import annotations

import time
from pathlib import Path

REPO_URL = "https://github.com/unxmaal/SoHoT"
PAGES = ("index.html", "reports/index.html", "benchmarks/index.html")

FONTS = ("https://fonts.googleapis.com/css2?family=Silkscreen:wght@400;700"
         "&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;600"
         "&display=swap")

CSS = """
:root { --desk:#f3d5df; --dot:#e9bccb; --win:#fdf6e6; --ink:#1d1b22; --dim:#5f5a55;
        --line:#1d1b22; --shadow:#1d1b22; --on:#1d1b22; --code:#f4ead2;
        --pink:#ffa3c6; --teal:#86d9cb; --butter:#ffe28f; --sky:#aed5ff; --lilac:#d5c2ff;
        --good:#1f5a37; --goodbg:#cdeedd; --warn:#7a5200; --warnbg:#ffefc2;
        --bad:#8a1f1f; --badbg:#ffd9d9; }
@media (prefers-color-scheme: dark) {
  :root { --desk:#1c1930; --dot:#2a2646; --win:#2b2840; --ink:#f3ead6; --dim:#b3abc4;
          --line:#0c0b14; --shadow:#07060c; --on:#141221; --code:#211e33;
          --pink:#e07aa3; --teal:#4fb3a2; --butter:#d6b552; --sky:#6e9fdc; --lilac:#9c86d6;
          --good:#9be8b8; --goodbg:#163626; --warn:#ffd27a; --warnbg:#3a2c09;
          --bad:#ffa3a3; --badbg:#3d1717; } }
* { box-sizing:border-box }
html { -webkit-text-size-adjust:100% }
body { margin:0; color:var(--ink); background-color:var(--desk);
       background-image:radial-gradient(var(--dot) 1.2px, transparent 1.3px);
       background-size:14px 14px;
       font:16px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; }
a { color:inherit }
code, pre, table { font-family:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace }
h1, h2, h3, .menubar, .btn, .num, .chip { font-family:"Silkscreen",ui-monospace,monospace;
       font-weight:400; letter-spacing:.02em }
.menubar { display:flex; flex-wrap:wrap; align-items:center; gap:.25rem 1.25rem;
           padding:.45rem 1rem; background:var(--win); border-bottom:2px solid var(--line);
           font-size:.85rem }
.menubar a { text-decoration:none; padding:.1rem .35rem }
.menubar a:hover, .menubar a[aria-current] { background:var(--ink); color:var(--win) }
.menubar .brand { font-weight:700; margin-right:auto }
main { max-width:64rem; margin:0 auto; padding:1.75rem 16px 3rem }
.win { background:var(--win); border:2px solid var(--line); box-shadow:5px 5px 0 var(--shadow);
       margin:0 0 1.75rem; min-width:0 }
.bar { display:flex; align-items:center; gap:.6rem; padding:5px 8px;
       border-bottom:2px solid var(--line); background-color:var(--tint, var(--win));
       background-image:repeating-linear-gradient(var(--line) 0 1px, transparent 1px 4px);
       background-origin:content-box; background-clip:content-box }
.bar .box { flex:none; width:15px; height:15px; border:2px solid var(--line);
            background:var(--win); box-shadow:0 0 0 3px var(--tint, var(--win)) }
.bar h2, .bar h1 { margin:0 auto; padding:0 .6rem; background:var(--tint, var(--win));
                   color:var(--on); font-size:.95rem; line-height:1.5; text-align:center;
                   overflow-wrap:anywhere }
.win:not([style*="--tint"]) .bar h2 { color:var(--ink) }
.body { padding:1rem 1.1rem 1.15rem; min-width:0 }
.body > :first-child { margin-top:0 }
.body > :last-child { margin-bottom:0 }
.pink { --tint:var(--pink) } .teal { --tint:var(--teal) } .butter { --tint:var(--butter) }
.sky { --tint:var(--sky) } .lilac { --tint:var(--lilac) }
.hero .body { text-align:center; padding:2rem 1.1rem 2.2rem }
.hero h1 { font-size:clamp(2.6rem, 12vw, 5rem); line-height:1; margin:.2rem 0 .4rem }
.hero .expand { font-family:"Silkscreen",monospace; font-size:clamp(.8rem, 3.2vw, 1.05rem);
                margin:0 0 1.1rem }
.lead { font-size:1.15rem; max-width:38rem; margin:0 auto 1.6rem }
.buttons { display:flex; flex-wrap:wrap; gap:1rem; justify-content:center }
.btn { display:inline-block; padding:.65rem 1.1rem; border:2px solid var(--line);
       box-shadow:3px 3px 0 var(--shadow); background:var(--pink); color:var(--on);
       text-decoration:none; font-size:.95rem }
.btn.alt { background:var(--teal) }
.btn:active { transform:translate(3px,3px); box-shadow:none }
.stats { display:grid; grid-template-columns:repeat(auto-fit, minmax(13rem, 1fr));
         gap:1.25rem; margin:0 0 1.75rem }
.stats .win { margin:0 }
.stats .body { text-align:center }
.num { display:block; font-size:2.4rem; line-height:1.1; margin:.2rem 0 .3rem }
.stat-label { display:block; font-weight:600 }
.where { display:block; color:var(--dim); font-size:.8rem; margin-top:.35rem;
         overflow-wrap:anywhere }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(17rem, 1fr));
         gap:1.25rem; margin:0 0 1.75rem }
.cards .win { margin:0 }
.cards h3 { font-size:.9rem; margin:0 0 .5rem }
.steps { list-style:none; counter-reset:step; padding:0; margin:0;
         display:grid; grid-template-columns:repeat(auto-fit, minmax(14rem, 1fr)); gap:.9rem }
.steps li { counter-increment:step; border:2px solid var(--line); padding:.6rem .75rem;
            background:var(--desk) }
.steps li::before { content:counter(step) ". "; font-family:"Silkscreen",monospace }
.steps b { font-family:"Silkscreen",monospace; font-weight:400 }
.chips { list-style:none; padding:0; margin:.6rem 0; display:flex; flex-wrap:wrap; gap:.4rem }
.chip { border:2px solid var(--line); padding:.05rem .45rem; background:var(--butter);
        color:var(--on); font-size:.8rem }
.chip.judged { background:var(--lilac) }
.chip a { text-decoration:none }
pre { background:var(--code); border:2px solid var(--line); padding:.75rem .9rem;
      overflow-x:auto; font-size:.85rem; line-height:1.45; margin:.4rem 0 1rem }
code { font-size:.92em }
h3 { font-size:.9rem; margin:1.4rem 0 .4rem }
.sub, .note, .dim { color:var(--dim) }
.sub { margin:0 0 .5rem }
.note { font-size:.88rem; margin:.5rem 0 0 }
.wide { overflow-x:auto; max-width:100%; margin:.4rem 0 }
table { border-collapse:collapse; width:100%; font-size:.82rem }
th, td { text-align:left; padding:.32rem .55rem; border:1px solid var(--line); vertical-align:top }
th { background:var(--desk); font-weight:600; white-space:nowrap }
td.num, .wide td.num { display:table-cell; font-family:inherit; font-size:inherit;
                       text-align:right; font-variant-numeric:tabular-nums; margin:0 }
.tag { display:inline-block; padding:0 .35rem; border:1px solid currentColor;
       font-size:.75rem; white-space:nowrap }
.warn { background:var(--warnbg); color:var(--warn) }
.bad { background:var(--badbg); color:var(--bad) }
.good { background:var(--goodbg); color:var(--good) }
tr.changed td { background:var(--goodbg) }
footer { text-align:center; color:var(--dim); font-size:.85rem; padding:0 16px 2.5rem }
"""


def _esc(x) -> str:
    from harness.report import _esc as esc
    return esc(x)


def _date(iso) -> str:
    return (iso or "")[:10] or "--"


def window(title: str, body: str, tint: str = "", cls: str = "", tag: str = "div",
           attrs: str = "") -> str:
    """A classic desktop window: striped title bar, close box, cream body."""
    klass = " ".join(c for c in ("win", tint, cls) if c)
    return (f'<{tag}{attrs} class="{klass}"><div class="bar"><span class="box"></span>'
            f'<h2>{title}</h2></div><div class="body">{body}</div></{tag}>')


def page(title: str, body: str, depth: int = 0, here: str = "", now: float | None = None) -> str:
    """The shared shell: fonts, theme, menu bar and footer."""
    up = "../" * depth
    links = (("", "SoHoT"), ("benchmarks/", "Benchmarks"), ("reports/", "Lane report"))
    menu = "".join(
        f'<a href="{up + href or "./"}"{" class=brand" if not href else ""}'
        f'{" aria-current=page" if href == here else ""}>{label}</a>'
        for href, label in links)
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(time.time() if now is None else now))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{_esc(FONTS)}">
<style>{CSS}</style></head>
<body>
<nav class="menubar">{menu}<a href="{REPO_URL}">Source</a></nav>
<main>
{body}
</main>
<footer>Built {_esc(when)} from each machine's own export.</footer>
</body></html>
"""


# --- the numbers -----------------------------------------------------------

def _where(docs: list[dict], dates=None) -> str:
    """'Mac Studio M5 Ultra 96 GB, 2026-10-06' per machine the number came from."""
    if not docs:
        return "no machine has published"
    return "; ".join(f"{d['machine'].get('label')}, "
                     f"{(dates or {}).get(id(d)) or _date(d.get('generated_at'))}"
                     for d in docs)


def _runs_span(doc: dict) -> str:
    days = sorted(_date(l.get("last_run_at")) for l in doc.get("lanes") or []
                  if l.get("comparison") and l.get("last_run_at"))
    if not days:
        return _date(doc.get("generated_at"))
    return days[0] if days[0] == days[-1] else f"runs {days[0]} to {days[-1]}"


def stats(machines: list[dict]) -> list[dict]:
    """The front page's numbers, each with the machines and dates it was computed from."""
    adopted_docs = [d for d in machines if any(l.get("adopted") for l in d.get("lanes") or [])]
    adopted = {l["lane"] for d in machines for l in d.get("lanes") or [] if l.get("adopted")}
    compared_docs = [d for d in machines if any(l.get("comparison") for l in d.get("lanes") or [])]
    compared = sum(len(l.get("comparison") or []) for d in machines
                   for l in d.get("lanes") or [])
    newest = max(machines, key=lambda d: d.get("generated_at") or "", default=None)
    return [
        {"key": "adopted", "value": str(len(adopted)),
         "label": "lanes with an adopted winner",
         "where": _where(adopted_docs or machines)},
        {"key": "compared", "value": str(compared),
         "label": "candidates compared in each lane's latest run",
         "where": _where(compared_docs or machines,
                         {id(d): _runs_span(d) for d in compared_docs})},
        {"key": "machines", "value": str(len(machines)),
         "label": "machines publishing", "where": _where(machines)},
        {"key": "latest", "value": _date(newest.get("generated_at")) if newest else "--",
         "label": "latest publish",
         "where": _where([newest]) if newest else "no machine has published"},
    ]


def lane_names(machines: list[dict]) -> list[str]:
    """Every lane the harness names, then any an export carries that it does not."""
    from harness import lanes
    out = list(lanes.ALL)
    for d in machines:
        for l in d.get("lanes") or []:
            if l.get("lane") and l["lane"] not in out:
                out.append(l["lane"])
    return out


# --- the front page --------------------------------------------------------

LOOP = (
    ("sweep", "Reads the model registries, the places practitioners talk, and what the "
              "people who build your tools star on GitHub."),
    ("inspect", "Reads each candidate's source or model card with nothing downloaded, and "
                "drops what cannot run on this machine."),
    ("fetch", "Downloads only what is queued, inside its own disk budget, and nothing "
              "more until you say so."),
    ("screen", "One minimal run that answers one question: did it run and emit anything."),
    ("measure", "The lane's full set of cases, paired against the model it would replace."),
    ("adopt", "Replaces the incumbent only on a significant paired win on held-out cases."),
)


def _stat_card(s: dict, tint: str) -> str:
    body = (f'<b class="num">{_esc(s["value"])}</b>'
            f'<span class="stat-label">{_esc(s["label"])}</span>'
            f'<span class="where">{_esc(s["where"])}</span>')
    return window(_esc(s["label"].split()[0]), body, tint, attrs=f' data-stat="{s["key"]}"')


def front(machines: list[dict], now: float | None = None) -> str:
    from harness import gateway, lanes, publish
    tints = ("pink", "teal", "butter", "sky")
    hero = window("SoHoT", (
        '<h1>SoHoT</h1>'
        '<p class="expand">Self-optimizing Harness of Theseus</p>'
        '<p class="lead">Local models for images, video, speech, music, SVG and code, '
        'and a harness that keeps replacing the model behind each job with a better one, '
        'but only when a measured run says it is better.</p>'
        '<div class="buttons"><a class="btn" href="benchmarks/">See the benchmarks</a>'
        '<a class="btn alt" href="reports/">Read the lane report</a></div>'),
        "pink", "hero")
    empty = ('<p class="note">No machine has published yet.</p>' if not machines else "")
    cards = "".join(_stat_card(s, tints[i % len(tints)]) for i, s in enumerate(stats(machines)))
    what = window("What is SoHoT?", (
        "<p>Like the ship of Theseus, every part of this harness gets replaced over time "
        "while the harness stays itself. The parts are the models serving each lane. "
        "SoHoT goes looking for challengers on its own, measures each one against the "
        "model it would replace on identical cases on your hardware, and swaps it in "
        "only on evidence. Nothing here was adopted because it was popular.</p>"
        "<p>It runs on your machine. No account, no API key, no per-token bill, and no "
        "model retired out from under you.</p>"), "sky")
    steps = "".join(f"<li><b>{name}</b><br>{_esc(text)}</li>" for name, text in LOOP)
    loop = window("The loop", (
        "<p>Each tier costs more than the last and only sees what survived the one "
        "before, so measurement is spent where it counts.</p>"
        f'<ol class="steps">{steps}</ol>'), "butter")
    chips = "".join(
        f'<li class="chip{" judged" if lanes.human_judged(n) else ""}">{_esc(n)}</li>'
        for n in lane_names(machines))
    judged = ", ".join(lanes.HUMAN_JUDGED)
    aliases = ", ".join(f"<code>{gateway.LANE_ALIAS.format(n)}</code>"
                        for n in gateway.TEXT_LANES)
    features = [
        ("The paired adopt gate", "pink",
         "<p>A challenger and the incumbent run the same held-out cases. The harness works "
         "out how many repeats the paired test needs to see a real gain, and a loss with "
         "too little power is recorded as underpowered, not as no better. Cases are split "
         "by content digest so nothing tunes itself on the cases that decide.</p>"),
        ("Lanes", "butter",
         "<p>A lane is one job with its own cases and checks. Each serves its own "
         f'winner:</p><ul class="chips">{chips}</ul>'
         f"<p class=\"note\">Highlighted lanes ({_esc(judged)}) have no metric that can "
         "pick a winner, so a person votes.</p>"),
        ("One gateway, stable names", "teal",
         "<p>An OpenAI-compatible gateway serves one alias per text lane: "
         f"{aliases}. An adoption re-points the alias to the winner without anyone "
         "editing a config, and without dropping a session in flight. Claude Code can "
         "use it through the Anthropic messages route.</p>"),
        ("A report per machine", "sky",
         "<p>Every machine keeps its own receipts and publishes its own slice, keyed by a "
         "hardware label and never a hostname. Paths are cut, and a privacy scan refuses "
         "any export that still names a person or a place. A machine that has not "
         f"published in {publish.STALE_DAYS:.0f} days is marked stale.</p>"),
        ("The gauntlet", "lilac",
         "<p>Every missed defect is traced to the logical failing behind it, which becomes "
         "a generic class with a test shape. Later code is tested against every class "
         "that has bitten, and CI fails new code that trips a detector until it has a "
         "test of its own.</p>"),
        ("It remembers", "pink",
         "<p>Every proposal, sighting and verdict goes into a small database, so a "
         "candidate already answered is not offered again, and one that lost stays "
         "lost until something about it changes.</p>"),
    ]
    feat = "".join(window(_esc(t), b, tint) for t, b, tint in features)
    quick = window("Quick start", (
        "<p>Install the command, <code>soh</code>, into its own environment:</p>"
        f"<pre><code>git clone {REPO_URL}\ncd SoHoT\n"
        "uv tool install --python 3.12 --editable .</code></pre>"
        "<p>Start the engine your machine has. On Apple Silicon:</p>"
        "<pre><code>./scripts/serve-mlx.sh &amp;        # inference engine\n"
        "./scripts/serve-gateway.sh &amp;    # the address clients use</code></pre>"
        "<p>On a machine with an NVIDIA card, one command starts all three:</p>"
        "<pre><code>./scripts/services.sh start     # gateway, text, audio</code></pre>"
        "<p>Then make something, and look for something better:</p>"
        "<pre><code>soh svg \"a settings gear icon\"\n"
        "soh discover --sweep            # read every source family\n"
        "soh discover --queue            # what a screen would teach, best first\n"
        "soh report                      # what each lane serves here, and why</code></pre>"
        "<p>Point Claude Code at the gateway:</p>"
        "<pre><code>ANTHROPIC_BASE_URL=http://&lt;host&gt;:4000 "
        "ANTHROPIC_AUTH_TOKEN=\"$SOHOT_GATEWAY_KEY\" \\\n  claude --model sohot-code</code></pre>"
        f'<p class="note">Everything else is in the <a href="{REPO_URL}#readme">README</a>.</p>'),
        "teal")
    body = (f'{hero}<div class="stats">{cards}</div>{empty}{what}{loop}'
            f'<div class="cards">{feat}</div>{quick}')
    return page("SoHoT", body, 0, "", now)


# --- the benchmarks --------------------------------------------------------

def _num(x, fmt="{:.2f}") -> str:
    return "--" if x is None else fmt.format(x)


def _bench_table(lane: dict) -> str:
    from harness import publish
    rows = []
    for r in lane.get("comparison") or []:
        tags = []
        if r.get("candidate") == lane.get("serves"):
            tags.append('<span class="tag good">serving</span>')
        if r.get("reference"):
            tags.append('<span class="tag">reference</span>')
        passed = (f'{r.get("passed")}/{r.get("total")} ' if r.get("total") else "")
        rows.append(
            f'<tr><td>{_esc(r.get("candidate"))} {" ".join(tags)}</td>'
            f'<td class="num">{_esc(passed)}{_num(r.get("pass_rate"))}</td>'
            f'<td class="num">{_num(r.get("median_s"))}</td>'
            f'<td class="num">{_num(r.get("first_s"))}</td>'
            f'<td class="num">{_num(r.get("peak_gb"), "{:.1f}")}</td>'
            f'<td>{_esc(publish._metric_text(r.get("metrics")))}</td></tr>')
    return ('<div class="wide"><table><tr><th>candidate</th><th>pass</th><th>median s</th>'
            '<th>first s</th><th>peak GB</th><th>metrics</th></tr>'
            f'{"".join(rows)}</table></div>')


def benchmarks(machines: list[dict], now: float | None = None) -> str:
    tints = ("pink", "teal", "butter", "sky", "lilac")
    by = [{l["lane"]: l for l in d.get("lanes") or [] if l.get("lane")} for d in machines]
    measured, waiting = [], []
    for n in lane_names(machines):
        (measured if any((b.get(n) or {}).get("comparison") for b in by) else waiting).append(n)
    index = "".join(f'<li class="chip"><a href="#lane-{_esc(n)}">{_esc(n)}</a></li>'
                    for n in measured)
    intro = window("Benchmarks", (
        "<p>Every lane's latest measure run, from each machine that published one. Each "
        "table is one run on one machine: the candidates in it ran the same cases under "
        "the same conditions. Wall-clock compares only within one machine; across "
        "machines, compare pass rates.</p>"
        + (f'<ul class="chips">{index}</ul>' if index else
           '<p class="note">No machine has published a measure run yet.</p>')), "sky")
    wins = []
    for i, n in enumerate(measured):
        parts = []
        for d, b in zip(machines, by):
            lane = b.get(n)
            if not lane or not lane.get("comparison"):
                continue
            parts.append(f'<h3>{_esc(d["machine"].get("label"))} &middot; run '
                         f'{_date(lane.get("last_run_at"))}</h3>{_bench_table(lane)}'
                         f'<p class="note">Serving here: {_esc(lane.get("serves")) or "--"}'
                         f'{" (adopted " + _esc(lane.get("adopted_how")) + ")" if lane.get("adopted") else ""}'
                         '</p>')
        wins.append(window(_esc(n), "".join(parts), tints[i % len(tints)],
                           attrs=f' id="lane-{_esc(n)}"'))
    rest = (window("Not measured yet", "<p>No published measure run for: "
                   + ", ".join(_esc(n) for n in waiting) + ".</p>", "lilac")
            if waiting and machines else "")
    return page("SoHoT benchmarks", intro + "".join(wins) + rest, 1, "benchmarks/", now)


# --- the whole site --------------------------------------------------------

def render(machines: list[dict], now: float | None = None) -> dict[str, str]:
    from harness import publish
    now = time.time() if now is None else now
    return {"index.html": front(machines, now),
            "reports/index.html": publish.render_site(machines, now=now),
            "benchmarks/index.html": benchmarks(machines, now)}


def write(machines: list[dict], out) -> list[Path]:
    out = Path(out)
    written = []
    for rel, html in render(machines).items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        written.append(p)
    return written
