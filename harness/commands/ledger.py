"""`soh ledger`: cloud vs local, what local displaced, and what it cost in power. #826."""
from __future__ import annotations

import shutil
import time

from harness.commands.common import emit, note


def _tok(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n:,}"


def tokens(t: dict | None) -> str:
    """Claude Code tokens as one phrase; a Max-plan login is not charged per token, so no price. #976."""
    if t is None:
        return "n/a"
    return (f"{_tok(t.get('input') or 0)} in, {_tok(t.get('output') or 0)} out, "
            f"{_tok(t.get('cache_read') or 0)} cache read, {_tok(t.get('cache_write') or 0)} cache write")


def local_tokens(b: dict | None) -> str:
    b = b or {}
    return f"{_tok(b.get('input') or 0)} in, {_tok(b.get('output') or 0)} out"


def gather(a, now: float) -> dict:
    """Every source read once; the store chosen by store.choose_read, read-only, each read's outcome kept. #1781."""
    from harness import context_report as cr, ledger, otel, store

    since = cr.parse_when(a.since, now)
    first_day = ledger.days_between(since, now)[0]
    week = ledger.days_between(now - ledger.RATIO_DAYS * 86400, now)[0]
    chosen = store.choose_read()
    try:
        reads, got = read_all(chosen, {"ledger_days": lambda c: ledger.recorded(c, min(first_day, week))})
        if getattr(a, "record", False):
            # A day a missed night or a DST shift left unrewritten is recorded again, not left short. #1776.
            first_day = min([first_day, *ledger.unsettled(got["ledger_days"])])
        start = ledger.day_start(first_day)
        more, rest = read_all(chosen, {
            "gateway_requests": lambda c: ledger.gateway_rows(c, start),
            "delegations": lambda c: ledger.delegation_rows(c, start),
            "otel_events": lambda c: otel.events(c, start, now + 1)})
        order = ("gateway_requests", "delegations", "ledger_days", "otel_events")
        reads = {k: {**reads, **more}[k] for k in order}
        got = {**got, **rest}
    finally:
        chosen.close()
    rows, dels, history, ev = (got[k] for k in ("gateway_requests", "delegations", "ledger_days", "otel_events"))
    root = cr.default_root()
    files = list(cr.transcripts(root, newer_than=start)) if root.is_dir() else []
    ctx = cr.scan(files, since=start)
    out = ledger.build(
        since=start, now=now, cloud_doc=ledger.cloud(first_day), rows=rows,
        limits=ledger.read_jsonl(ledger.ledger_dir() / "ratelimits.jsonl"),
        power=ledger.read_jsonl(ledger.ledger_dir() / "power.jsonl"),
        tariff=a.tariff, macmon=bool(shutil.which("macmon")), delegations=dels, context=ctx,
        macmon_version=ledger.macmon_version(), census_doc=ledger.census(), events=ev,
        messages=ledger.usage_messages(files, start),
        recorded_ratio={h["day"]: h["ratio"] for h in history if h.get("ratio")})
    out["recorded"] = [h for h in history if h["day"] >= first_day]
    out["otel"] = otel_days(ev)
    out["store"], out["reads"] = chosen.as_dict(), reads
    return out


def read_all(chosen, readers: dict) -> tuple[dict, dict]:
    """Each reader's outcome (answered with its row count, or why not) and rows, [] only beside an outcome that says so."""
    from harness import store
    reads, got = {}, {}
    for name, fn in readers.items():
        got[name] = []
        if chosen.conn is None:
            reads[name] = {"outcome": chosen.outcome, "why": chosen.why}
            continue
        try:
            got[name] = fn(chosen.conn)
        except store.Unread as u:
            reads[name] = {"outcome": u.outcome, "why": u.why}
            continue
        reads[name] = {"outcome": store.ANSWERED, "rows": len(got[name])}
    return reads, got


def unread(L: dict) -> list[str]:
    """Why this ledger may not be recorded: a store that is not the live one, or any read that did not answer."""
    from harness import store
    s = L.get("store") or {}
    out = [] if s.get("live") else [f"not the live store: {s.get('why_not_live') or s.get('why') or 'unknown'}"]
    out += [f"{name} {r['outcome']}: {r.get('why', '')}" for name, r in (L.get("reads") or {}).items()
            if r["outcome"] != store.ANSWERED]
    return out if L.get("reads") else out + ["no read was made"]


def otel_days(ev: list[dict], tz=None) -> dict:
    """Per local day, what Claude Code's own export says it spent. #868."""
    from harness import ledger, otel
    by_day: dict = {}
    for e in ev:
        by_day.setdefault(ledger.day_of(e["at"], tz), []).append(e)
    return {d: otel.from_events(rows) for d, rows in sorted(by_day.items())}


def show(L: dict) -> None:
    from harness import ledger
    w, s = L["window"], L["assumptions"]
    gw = (L.get("reads") or {}).get("gateway_requests") or {"outcome": "answered"}
    if gw["outcome"] != "answered":
        note(f"local:cloud UNREAD: gateway_requests {gw['outcome']}: {gw.get('why', '')}")
    else:
        note(ledger.ratio_line(L["ratio"]))
    if "store" in L:
        from harness import store
        note(f"store     {store.describe(L['store'])}")
    note(f"ledger {w['first_day']} .. {w['last_day']}")
    for line in cloud_lines(L["cloud"]):
        note(line)
    od = L.get("otel") or {}
    if od:
        note(f"otel      {tokens(_otel_sum(od))} over {sum(d['requests'] for d in od.values()):,} "
             f"api_request events, {sum(d['sessions'] for d in od.values())} session-days (Claude Code's own count)")
    else:
        note("otel      no rows; `soh otel env` prints the settings.json env that turns export on")
    h = L["headroom"]
    if h.get("available"):
        lt = h["latest"]
        parts = [f"{lab} {lt[k]:.0f}%" for k, lab in (("five_hour", "5h"), ("seven_day", "7d"))
                 if lt.get(k) is not None]
        note(f"plan      latest {', '.join(parts)} ({h['samples']} readings)")
    else:
        note(f"plan      {h.get('why')}")
    for p, b in L["local"].items():
        kind = "displaced" if p == "work" else "cost" if p in ("eval", "smoke") else "not counted"
        note(f"local     {p:<9} {b['requests']:>7,} reqs {_tok(b['input']):>8} in {_tok(b['output']):>8} out  ({kind})")
    if gw["outcome"] != "answered":
        note(f"local     UNREAD gateway_requests {gw['outcome']}: {gw.get('why', '')}")
    elif not L["local"]:
        note("local     none: no gateway requests in the window")
    for name, r in (L.get("reads") or {}).items():
        if name != "gateway_requests" and r["outcome"] not in ("answered", (L.get("store") or {}).get("outcome")):
            note(f"UNREAD    {name} {r['outcome']}: {r.get('why', '')}")
    dg = L["delegated"]
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(dg["outcomes"].items())) or "none"
    note(f"delegated {dg['requests']:,} requests inside work, joined on call_id (outcomes: {outcomes})"
         + (f"; {dg['unjoined']['requests']} with no gateway row, not counted" if dg["unjoined"]["requests"] else ""))
    if L.get("zero_delegation_days"):
        note(f"FLAG      cloud work and zero delegations on {', '.join(L['zero_delegation_days'])}: "
             "nothing went to local_complete, local_decide or `soh local`")
    for line in accepted_lines(L.get("accepted") or {}):
        note(line)
    note(f"displaced {local_tokens(L['displaced']['tokens'])} of tagged work served locally")
    if L["mapped"]["tokens"]["requests"]:
        note(f"mapped    {local_tokens(L['mapped']['tokens'])} of untagged history by alias mapping")
        for m in s["mapping"]:
            note(f"          {m['alias']} {m['first_day']}..{m['last_day']} -> {m['purpose']}: {m['why']}")
    e = L["energy"]
    if e.get("partial"):
        note(f"energy    PARTIAL: at least {e['lower_bound_kwh']:.2f} kWh without the CPU, "
             f"over {e['covered_s'] / 3600:.1f} h covered; {e['why']}")
    elif e.get("available"):
        note(f"energy    {e['kwh']:.2f} kWh, ${e['usd']:,.2f} at ${e['tariff_usd_per_kwh']}/kWh "
             f"(mean {e['mean_watts'] or 0:.0f} W over {e['covered_s'] / 3600:.1f} h covered)")
    else:
        note(f"energy    {e.get('why')}")
    if e.get("available"):
        note(f"          {energy_scope(e)}")
    note("")
    note(f"{'day':<10} {'source':<18} {'cloud in':>9} {'cloud out':>9} {'cache rd':>9} {'displaced':>9} "
         f"{'eval out':>9} {'unknown out':>11} {'kWh':>7} {'5h peak':>7} {'7d peak':>7}")
    for d in L["days"]:
        loc = d["local"]
        en = d["energy"] or {}
        ct = d["cloud"]["tokens"]
        cell = (lambda k: "n/a" if ct is None else _tok(ct.get(k) or 0))  # noqa: E731
        peaks = ["" if d["headroom"].get(k) is None else f"{d['headroom'][k]:.0f}%" for k in ("five_hour", "seven_day")]
        dt = d["displaced"]["tokens"]
        note(f"{d['day']:<10} {source_cell(d['cloud']):<18} {cell('input'):>9} {cell('output'):>9} {cell('cache_read'):>9} "
             f"{_tok(dt['input'] + dt['output']):>9} "
             f"{_tok(loc.get('eval', {}).get('output', 0)):>9} {_tok(loc.get('unknown', {}).get('output', 0)):>11} "
             f"{kwh_cell(en):>7} {peaks[0]:>7} {peaks[1]:>7}")
    note("\nClaude Code on a subscription is counted in tokens and plan-window use, not priced (#976)")


def cloud_lines(c: dict) -> list[str]:
    """The cloud total with the days each source counted, then ccusage's total as the cross-check. #1160."""
    if not c.get("available"):
        return [f"cloud     unavailable: {c.get('why')}"]
    cc = c.get("ccusage") or {}
    name = {"ccusage": cc.get("source") or "ccusage"}
    by = ", ".join(f"{name.get(s, s)} {n} day{'s' if n != 1 else ''}" for s, n in sorted(c["sources"].items()))
    out = [f"cloud     {tokens(c['tokens'])} ({by})"]
    if c.get("lower_bound"):
        out.append(f"          lower bound: {c['note']}")
    out.append(f"          {cc.get('source', 'ccusage')}: " + (tokens(cc["tokens"]) if cc.get("available")
                                                              else f"unavailable: {cc.get('why')}"))
    return out


def accepted_lines(A: dict) -> list[str]:
    """The accepted-share line, then one per lane against the census's cloud subtasks of its shape. #1158."""
    t = A.get("total") or {}
    share = A.get("accepted_share")
    out = [f"accepted  share {'n/a' if share is None else f'{share:.0%}'} of closed delegations: "
           f"{t.get('accepted', 0)} accepted, {t.get('rejected', 0)} rejected, {t.get('unknown', 0)} unknown, "
           f"{t.get('pending', 0)} pending"]
    cen = A.get("census") or {}
    for lane, b in (A.get("lanes") or {}).items():
        if b["cloud_per_day"] is None:
            vs = (f"no census shape for {lane}" if not b["shapes"] else f"census unavailable: {cen.get('why')}")
        else:
            vs = (f"vs {b['cloud_per_day']:.1f} cloud {'+'.join(b['shapes'])} subtasks/day, local share "
                  f"{b['local_share']:.1%}" if b["local_share"] is not None else "no tasks of that shape")
        out.append(f"          {lane:<8} {b['accepted']} accepted, {b['per_day']:.2f}/day; {vs}")
    return out


def source_cell(c: dict) -> str:
    """Which source counted a day's cloud tokens, with '>=' when that is a lower bound. #1160."""
    if not c.get("source"):
        return "-"
    return (">=" if c.get("lower_bound") else "") + c["source"]


def kwh_cell(en: dict) -> str:
    """A day's kWh, or 'partial' when its CPU was not read. #1005."""
    if en.get("partial"):
        return "partial"
    return f"{en.get('kwh') or 0:.2f}"


def energy_scope(e: dict) -> str:
    """What the power figure covers, and how many readings were dropped as a counter catching up."""
    what = {"soc": "SoC power (CPU, GPU, ANE): no DRAM, SSD, fans or PSU loss, so below wall power",
            "system": "macmon system power (SMC PSTR)"}.get(e.get("scope"), "macmon power")
    drop = e.get("implausible") or 0
    return what + (f"; {drop} readings above {e['ceiling_w']:.0f} W dropped" if drop else "")


def _otel_sum(od: dict) -> dict:
    return {k: sum(d.get(k) or 0 for d in od.values()) for k in ("input", "output", "cache_read", "cache_write")}


def gather_compare(day: str, tz=None) -> dict:
    """One day from every source: OTel events and metrics, ccusage, transcripts. #868."""
    from harness import context_report as cr, ledger, otel, store
    import datetime as _dt
    start = ledger.day_start(day, tz)
    end = ledger.day_start((_dt.date.fromisoformat(day) + _dt.timedelta(days=1)).isoformat(), tz)
    picked = store.choose_read()
    try:
        reads, got = read_all(picked, {"otel_events": lambda c: otel.events(c, start, end),
                                       "otel_metrics": lambda c: otel.metrics(c, start, end)})
    finally:
        picked.close()
    ev, mt = got["otel_events"], got["otel_metrics"]
    cc = ledger.cloud(day)
    root = cr.default_root()
    files = list(cr.transcripts(root, newer_than=start)) if root.is_dir() else []
    ctx = cr.scan(files, since=start, until=end)
    msgs = ledger.usage_messages(files, start, end)
    chosen = ledger.cloud_days([day], cc, ev, msgs, tz)[day]
    usage = {**ledger._by_model(msgs, ledger._msg_tokens)[0], "requests": len(msgs)} if msgs else None
    C = otel.compare(day, ev, mt, (cc.get("days") or {}).get(day), ctx,
                     ccusage_available=bool(cc.get("available")), usage=usage, chosen=chosen)
    g = ledger.gap(ev, msgs)
    C["gap"], C["source"] = g, {k: chosen.get(k) for k in ("source", "lower_bound", "outside_messages")}
    C["notes"]["ledger"] = (f"counts {chosen['source'] or 'nothing'}"
                            + (" (a lower bound)" if chosen["lower_bound"] else ""))
    if g["ratio"] is not None:
        C["notes"]["gap"] = (f"OTel output {g['otel_output']:,} over {g['otel_requests']:,} requests is "
                             f"{g['ratio']:.2f}x the transcripts' {g['transcript_output']:,} over the "
                             f"{g['transcript_messages']:,} messages they kept of the same requests")
    C["notes"]["store"] = picked.line()
    for name, r in reads.items():
        if r["outcome"] != store.ANSWERED:
            C["notes"][name] = f"UNREAD {r['outcome']}: {r['why']}"
    C["store"], C["reads"] = picked.as_dict(), reads
    return C


def _cell(v) -> str:
    return "-" if v is None else f"{int(v):,}"


def show_compare(C: dict) -> None:
    from harness import otel
    note(f"compare {C['day']}")
    note(f"{'':<26}" + "".join(f"{s:>16}" for s in otel.SOURCES))
    for r in C["rows"]:
        note(f"{r['label']:<26}" + "".join(f"{_cell(r[s]):>16}" for s in otel.SOURCES))
    if C["models"]:
        note("\ntokens by model")
        for m in C["models"]:
            note(f"{m['model'][:26]:<26}" + "".join(f"{_cell(m.get(s)):>16}" for s in otel.SOURCES))
    for k, v in C["notes"].items():
        note(f"{k}: {v}")


def asked_days(specs: list[str]) -> list[str]:
    """Each --day as one day or a FIRST..LAST range, sorted and once each; ValueError on a bad one."""
    import datetime as _dt
    out: set[str] = set()
    for spec in specs:
        first, _, last = spec.partition("..")
        a, b = _dt.date.fromisoformat(first), _dt.date.fromisoformat(last or first)
        if b < a:
            raise ValueError(f"--day {spec}: the range ends before it starts")
        out.update((a + _dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1))
    return sorted(out)


def _counts(r: dict | None) -> str:
    if not r:
        return "no count"
    loc, cloud = ("not counted" if r.get(k) is None else _tok(r[k]) for k in ("local", "cloud"))
    return f"local {loc} cloud {cloud}"


def _when(at) -> str:
    return "never" if at is None else time.strftime("%Y-%m-%d %H:%M", time.localtime(float(at)))


def cmd_days(a, now: float) -> int:
    """`--day`: rewrite each named short day, leave complete ones alone, refuse one still open; dry without --record. #1941."""
    import argparse
    from harness import ledger
    try:
        days = asked_days(a.day)
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    still = [d for d in days if ledger.settled_at(d) > now]
    if still:
        why = "; ".join(f"{d} is still open until {_when(ledger.settled_at(d))}" for d in still)
        note(f"--day refused, nothing read or written: {why}; the nightly --record rewrites it")
        emit(False, error="day still open", open=still)
        return 2
    import datetime as _dt
    since = _dt.datetime.fromtimestamp(ledger.day_start(days[0])).astimezone().isoformat()
    L = gather(argparse.Namespace(**{**vars(a), "since": since, "record": False}), now)
    plan = ledger.rewrite_plan(days, L["recorded"], L["days"])
    from harness import store
    note(f"store     {store.describe(L['store'])}")
    for p in plan:
        note(f"{p['day']} {p['state']:<10} last written {_when(p['recorded_at'])}: "
             f"before {_counts(p['before'])}; recount {_counts(p['after'])}")
    short = [p["day"] for p in plan if p["state"] == ledger.SHORT]
    out = {"rewrite": plan, "store": L["store"], "reads": L["reads"]}
    refused = unread(L)
    if refused:
        note("UNREAD: " + "; ".join(refused))
    if not a.record:
        note(f"dry run: {len(short)} short day(s) would be rewritten; --record writes them")
        emit(**out)
        return 0
    if refused:
        note("--record refused, nothing written to ledger_days")
        emit(False, error="record refused", refused=refused, **out)
        return 1
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        n = ledger.record(conn, {"days": [d for d in L["days"] if d["day"] in short]}, now)
    finally:
        conn.close()
    note(f"rewrote {n} short day(s) in ledger_days: {', '.join(short) or 'none'}")
    emit(recorded=short, **out)
    return 0


def cmd_ledger(a) -> int:
    from harness import ledger

    now = time.time()
    if getattr(a, "day", None):
        return cmd_days(a, now)
    if getattr(a, "compare", ""):
        try:
            C = gather_compare(a.compare)
        except ValueError as exc:
            note(str(exc))
            emit(False, error=str(exc))
            return 2
        show_compare(C)
        emit(**C)
        return 0
    if a.sample_power:
        got = ledger.sample_power()
        note(f"{got['watts']:.1f} W" if got["ok"] else got["why"])
        emit(got["ok"], **{k: v for k, v in got.items() if k != "ok"})
        return 0 if got["ok"] else 1
    try:
        L = gather(a, now)
    except ValueError as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    show(L)
    if a.record:
        refused = unread(L)
        if refused:
            note("--record refused, nothing written to ledger_days: " + "; ".join(refused))
            emit(False, error="record refused", refused=refused, **L)
            return 1
        from harness import memory_store as ms
        conn = ms.connect()
        try:
            n = ledger.record(conn, L, now)
        finally:
            conn.close()
        note(f"recorded {n} days in ledger_days")
    emit(**L)
    return 0
