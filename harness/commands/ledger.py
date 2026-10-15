"""`soh ledger`: cloud vs local, what local displaced, and what it cost in power. #826."""
from __future__ import annotations

import shutil
import time

from harness.commands.common import emit, note


def _usd(v) -> str:
    return "n/a" if v is None else f"${v:,.2f}"


def _tok(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1_000_000 else f"{n:,}"


def gather(a, now: float) -> dict:
    """Every source read once; the live store only through a read-only connection."""
    from harness import context_report as cr, ledger, memory_store as ms, otel, store

    since = cr.parse_when(a.since, now)
    first_day = ledger.days_between(since, now)[0]
    start = ledger.day_start(first_day)
    rows, dels, history, ev = [], [], [], []
    if store.backend() == store.POSTGRES:
        conn = ms.connect()
    else:
        path = ms.db_path()
        conn = ledger.open_ro(path) if path.exists() else None
    if conn is not None:
        try:
            rows = ledger.gateway_rows(conn, start)
            dels = ledger.delegation_rows(conn, start)
            history = ledger.recorded(conn, first_day)
            ev = otel.events(conn, start, now + 1)
        finally:
            conn.close()
    pin = ledger.pin("LITELLM_PIN")
    table = ledger.prices(pin)
    root = cr.default_root()
    ctx = cr.scan(cr.transcripts(root, newer_than=start), since=start) if root.is_dir() else []
    out = ledger.build(
        since=start, now=now, cloud_doc=ledger.cloud(first_day, table=table, litellm_pin=pin), rows=rows,
        limits=ledger.read_jsonl(ledger.ledger_dir() / "ratelimits.jsonl"),
        power=ledger.read_jsonl(ledger.ledger_dir() / "power.jsonl"),
        table=table, tier=a.tier, tariff=a.tariff,
        macmon=bool(shutil.which("macmon")), litellm_pin=pin, delegations=dels, context=ctx)
    out["recorded"] = history
    out["otel"] = otel_days(ev)
    return out


def otel_days(ev: list[dict], tz=None) -> dict:
    """Per local day, what Claude Code's own export says it spent. #868."""
    from harness import ledger, otel
    by_day: dict = {}
    for e in ev:
        by_day.setdefault(ledger.day_of(e["at"], tz), []).append(e)
    return {d: otel.from_events(rows) for d, rows in sorted(by_day.items())}


def show(L: dict) -> None:
    w, s = L["window"], L["assumptions"]
    note(f"ledger {w['first_day']} .. {w['last_day']}")
    c = L["cloud"]
    if c.get("available"):
        unpriced = ", ".join(c.get("unpriced_models") or []) or "none"
        note(f"cloud     {_usd(c['usd'])} Claude Code API-equivalent ({c['source']}); "
             f"unpriced, not counted: {unpriced}")
        if c.get("litellm_priced_models"):
            note(f"          priced from {c.get('litellm_price_source')} (ccusage has no price): "
                 f"{', '.join(c['litellm_priced_models'])}")
    else:
        note(f"cloud     unavailable: {c.get('why')}")
    od = L.get("otel") or {}
    if od:
        note(f"otel      {_usd(sum(d['usd'] for d in od.values()))} over {sum(d['requests'] for d in od.values()):,} "
             f"api_request events, {sum(d['sessions'] for d in od.values())} session-days (Claude Code's own figure)")
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
    if not L["local"]:
        note("local     no gateway requests in the window")
    dg = L["delegated"]
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(dg["outcomes"].items())) or "none"
    note(f"delegated {dg['requests']:,} requests inside work, joined on call_id (outcomes: {outcomes})"
         + (f"; {dg['unjoined']['requests']} with no gateway row, not priced" if dg["unjoined"]["requests"] else ""))
    note(f"displaced {_usd(L['displaced']['usd'])} of tagged work at {L['displaced']['tier']}")
    if L["mapped"]["usd"]:
        note(f"mapped    {_usd(L['mapped']['usd'])} of untagged history by alias mapping, "
             f"at {L['mapped']['tier']}")
        for m in s["mapping"]:
            note(f"          {m['alias']} {m['first_day']}..{m['last_day']} -> {m['purpose']}: {m['why']}")
    e = L["energy"]
    if e.get("available"):
        note(f"energy    {e['kwh']:.2f} kWh, {_usd(e['usd'])} at ${e['tariff_usd_per_kwh']}/kWh "
             f"(mean {e['mean_watts'] or 0:.0f} W over {e['covered_s'] / 3600:.1f} h covered)")
    else:
        note(f"energy    {e.get('why')}")
    note("")
    note(f"{'day':<10} {'cloud':>10} {'displaced':>10} {'mapped':>10} {'work out':>9} "
         f"{'eval out':>9} {'unknown out':>11} {'kWh':>6} {'7d peak':>7}")
    for d in L["days"]:
        loc = d["local"]
        en = d["energy"] or {}
        peak = d["headroom"].get("seven_day")
        note(f"{d['day']:<10} {_usd(d['cloud']['usd']):>10} {_usd(d['displaced']['usd']):>10} "
             f"{_usd(d['mapped']['usd']):>10} {_tok(loc.get('work', {}).get('output', 0)):>9} "
             f"{_tok(loc.get('eval', {}).get('output', 0)):>9} {_tok(loc.get('unknown', {}).get('output', 0)):>11} "
             f"{en.get('kwh', 0):>6.2f} {'' if peak is None else f'{peak:.0f}%':>7}")
    note(f"\ntier assumed: {s['counterfactual_default']}; prices {s['price_source']}")


def gather_compare(day: str, tz=None) -> dict:
    """One day from every source: OTel events and metrics, ccusage, transcripts. #868."""
    from harness import context_report as cr, ledger, otel
    from harness.commands.context import _read_conn
    import datetime as _dt
    start = ledger.day_start(day, tz)
    end = ledger.day_start((_dt.date.fromisoformat(day) + _dt.timedelta(days=1)).isoformat(), tz)
    ev, mt = [], []
    conn = _read_conn()
    if conn is not None:
        try:
            ev, mt = otel.events(conn, start, end), otel.metrics(conn, start, end)
        finally:
            conn.close()
    pin = ledger.pin("LITELLM_PIN")
    cc = ledger.cloud(day, table=ledger.prices(pin), litellm_pin=pin)
    root = cr.default_root()
    ctx = cr.scan(cr.transcripts(root, newer_than=start), since=start, until=end) if root.is_dir() else []
    return otel.compare(day, ev, mt, (cc.get("days") or {}).get(day), ctx,
                        ccusage_available=bool(cc.get("available")))


def _cell(row: str, v) -> str:
    if v is None:
        return "-"
    return _usd(v) if row == "usd" else f"{int(v):,}"


def show_compare(C: dict) -> None:
    from harness import otel
    note(f"compare {C['day']}")
    note(f"{'':<26}" + "".join(f"{s:>16}" for s in otel.SOURCES))
    for r in C["rows"]:
        note(f"{r['label']:<26}" + "".join(f"{_cell(r['row'], r[s]):>16}" for s in otel.SOURCES))
    if C["models"]:
        note("\ncost by model")
        for m in C["models"]:
            note(f"{m['model'][:26]:<26}" + "".join(f"{_cell('usd', m.get(s)):>16}" for s in otel.SOURCES))
    for k, v in C["notes"].items():
        note(f"{k}: {v}")


def cmd_ledger(a) -> int:
    from harness import ledger

    now = time.time()
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
    if a.record:
        from harness import memory_store as ms
        conn = ms.connect()
        try:
            n = ledger.record(conn, L, now)
        finally:
            conn.close()
        note(f"recorded {n} days in ledger_days")
    show(L)
    emit(**L)
    return 0
