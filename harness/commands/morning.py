"""`soh morning`: one report of last night, with a notification only when something needs a person. #867."""
from __future__ import annotations

import time
from datetime import datetime

from harness.commands.common import emit, note


def _hm(t) -> str:
    return datetime.fromtimestamp(float(t)).strftime("%m-%d %H:%M") if t else "--"


def ledger_line(led: dict) -> str:
    """Last night's ledger row: Claude in tokens and plan-window peaks, local work in tokens. #976."""
    from harness.commands.ledger import local_tokens, tokens
    pe = led.get("energy") or {}
    kwh = ("n/a" if led["energy_kwh"] is None else f"{led['energy_kwh']:.2f} kWh") if not pe.get("partial") else \
        f"PARTIAL, at least {pe.get('lower_bound_kwh') or 0:.2f} kWh without the CPU ({(pe.get('why') or '').split(';')[0]})"
    plan = ", ".join(f"{lab} {led['plan'][k]:.0f}%" for k, lab in (("five_hour", "5h"), ("seven_day", "7d"))
                     if led["plan"].get(k) is not None) or "no readings"
    src = led.get("cloud_source")
    src = f" ({'at least, ' if led.get('cloud_lower_bound') else ''}{src})" if src else ""
    return (f"ledger    {led['day']}: cloud {tokens(led['cloud'])}{src}; plan peak {plan}; "
            f"displaced {local_tokens(led['displaced'])}, energy {kwh} (recorded {_hm(led['recorded_at'])})")


def api_spend_line(s: dict | None) -> str:
    """The API credit ledger, the one ledger reported in dollars (#1214); "" before schema 83."""
    if s is None:
        return ""
    from harness import api_spend
    return f"api spend {api_spend.line(s)}"


def _tally(d: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "none"


def diversity_lines(got) -> list[str]:
    """The night's diversity picks with their family, else what the measure step said of its reserved slots. #1111."""
    if not got:
        return []
    picks = got.get("picks") or []
    if picks:
        return [f"diversity {p['name']} took a reserved slot: family {p['why']}" for p in picks]
    return [f"diversity {ln.split(': ', 1)[-1]}" for ln in (got.get("lines") or [])[-1:]]


def render(r: dict) -> list[str]:
    """The deterministic report, one line per fact."""
    s = r["sweep"]
    out = [f"since {_hm(r['since'])}"]
    h = r.get("lane") or {}
    from harness import morning
    from harness.availability import incident_line
    if h and morning.open_incident(r, h["lane"]) is None:
        state = {True: "generating", False: "CANNOT GENERATE"}.get(h.get("generating"), f"unknown ({h.get('why')})")
        out.append(f"lane      {h['lane']}: {state}")
    inc = r.get("incumbent")
    if inc:
        out.append(f"incumbent {inc['lane']}: {inc['spec']} ({inc['source']})"
                   + (f"; {inc['detail']}" if inc.get("detail") else ""))
    out.append(f"incidents {len(r.get('incidents') or [])}")
    out.extend(f"          {incident_line(i)}" for i in r.get("incidents") or [])
    loop = s.get("loop")
    if loop is None:
        out.append("sweep     no loop heartbeat")
    else:
        when = "" if loop["in_window"] else " (not last night)"
        out.append(f"sweep     started {_hm(loop['started'])}{when}; {loop['line']}")
        if loop.get("ceiling_unused"):
            out.append(f"ceiling   {morning.unused_line(loop['ceiling_unused'])}")
        out.extend(diversity_lines(loop.get("diversity")))
    checks = r.get("checks") or []
    out.append(f"checks    {len(checks)} sweep check(s)")
    out.extend(f"          {_hm(c['at'])} {c['verdict']:<14} {c['line']}{' [notified]' if c['notified'] else ''}"
               for c in checks)
    out.append(f"screened  {_tally(s['screened'])}")
    runs = s["measured"]["runs"]
    out.append(f"measured  {len(runs)} run(s){': ' + ', '.join(x['lane'] for x in runs) if runs else ''}; "
               f"verdicts {_tally(s['measured']['verdicts'])}")
    for p in s["paused"]:
        out.append(f"paused    #{p['id']} {p['lane']} {p['challenger']} {p['state']} at {p['done']}/{p['total']} "
                   f"({_hm(p['paused_at'])})")
    if not s["paused"]:
        out.append("paused    none")
    out.append(f"stopped   {len(s['stopped'])}"
               + "".join(f"\n          {_hm(w['at'])} {w['criterion']} on {w['subject']}: {w['outcome']}"
                         for w in s["stopped"]))
    adopted = s["settled"]["adopted"]
    out.append(f"settled   {_tally(s['settled']['verdicts'])}"
               + (f"; adopted {', '.join(a['lane'] + ' ' + a['spec'] for a in adopted)}" if adopted else ""))
    out.extend(f"cleared   {c['line']}; {c['skips']} day limit(s) let off" for c in r.get("clearances") or [])
    out.append(f"watchdog  {len(r['watchdog'])} action(s)")
    for w in r["watchdog"]:
        flags = ("escalated " if w["escalated"] else "") + ("dry-run" if w["dry_run"] else "acted")
        out.append(f"          {_hm(w['at'])} {w['action']:<6} {w['criterion']} on {w['subject']} [{flags}]: "
                   f"{w['outcome']}")
        out.extend(f"            client {c}" for c in w.get("clients") or [])
    c = r["ci"]
    if not c.get("available"):
        out.append(f"nightly   unavailable: {c.get('why')}")
    else:
        age = "" if c["fresh"] else " (not last night's)"
        out.append(f"nightly   run {c['id']} {c['status']} {c['conclusion'] or '-'} at {_hm(c['created'])}{age} "
                   f"on {c['sha'][:8]}")
        for j in c["jobs"]:
            out.append(f"          {j['conclusion'] or j['status']:<10} {j['name']}")
    led = r["ledger"]
    if led is None:
        out.append("ledger    no ledger_days table")
    elif led.get("missing"):
        out.append(f"ledger    no row for {led['day']}")
    else:
        out.append(ledger_line(led))
    if api_spend_line(r.get("api_spend")):
        out.append(api_spend_line(r.get("api_spend")))
    fams = r.get("families") or []
    out.append(f"families  {len(fams)} demoted in a lane by paired losses")
    out.extend(f"          {f['lane']:<9} {f['family']}: {f['losses']} member(s) lost since its last win "
               f"({', '.join(f['lost'][:3])}{', ...' if len(f['lost']) > 3 else ''}); the rest rank lower"
               for f in fams)
    if r.get("yield"):
        from harness import yield_stop
        out.append("yield     stop points, in generated tokens")
        out.extend(f"          {yield_stop.line(y)}" for y in r["yield"])
    out.append(f"stale     {len(r['stale'])} lane(s)")
    for t in r["stale"]:
        out.append(f"          {t['lane']:<9} {t['candidate'][:40]} {t['skip'] or t['why']}")
    out.append(f"stalled   {len(r.get('stalled') or [])} ranked-head candidate(s)")
    for t in r.get("stalled") or []:
        out.append(f"          {t['lane']:<9} #{t['lane_rank']} {t['name'][:40]} {t['stage']} "
                   f"{t['in_state_days']:.0f}d: {t['reason']}: {t['why']}")
    out.append(f"runtimes  {len(r.get('runtimes') or [])} upgrade verdict(s)")
    from harness import runtime_trials
    out.extend(f"          {runtime_trials.line(v)}" for v in r.get("runtimes") or [])
    if r.get("canary"):
        out.append(f"canary    {r['canary']}")
    if r.get("parked"):
        out.append("nodes     " + ", ".join(f"{n} parked" for n in r["parked"]))
    d = r["deploy"]
    if not d.get("available"):
        out.append(f"deploy    unavailable: {d.get('why')}")
    else:
        out.append(f"deploy    {d['head'][:8]} vs origin/main {d['main'][:8]}: "
                   + (f"{d['behind']} commit(s) behind" if d["behind"] else "current"))
        out.extend(f"          {m}" for m in d["missing"])
    return out


def cmd_morning(a) -> int:
    from harness import canary, context_report as cr, heartbeat, morning, paths

    now = time.time()
    try:
        since = cr.parse_when(a.since, now)
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    conn = morning.snapshot()
    try:
        r = morning.gather(conn, now, since, beat=heartbeat.summary(), where=paths.deploy_checkout(),
                           health=morning.lane_health, canary=canary.morning_line, parked=morning.parked_nodes,
                           incumbent=morning.repo_incumbent)
    finally:
        conn.close()
    lines = render(r)
    head = morning.headline(r, "\n".join(lines), ask=None if a.no_model else morning._ask)
    r["headline"] = head
    r["notified"] = morning.notify(r, head["text"]) if a.notify else None
    for ln in head["text"].splitlines():
        note(ln)
    note(f"({'condensed by the local model' if head['by'] == 'model' else 'deterministic: ' + head['why']})\n")
    for ln in lines:
        note(ln)
    if r["needs"]:
        note("\nneeds a person:")
        for n in r["needs"]:
            note(f"  - {n}")
    if r["notified"]:
        note(r["notified"])
    emit(**r)
    return 0
