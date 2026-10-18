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
    root = cr.default_root()
    ctx = cr.scan(cr.transcripts(root, newer_than=start), since=start) if root.is_dir() else []
    out = ledger.build(
        since=start, now=now, cloud_doc=ledger.cloud(first_day), rows=rows,
        limits=ledger.read_jsonl(ledger.ledger_dir() / "ratelimits.jsonl"),
        power=ledger.read_jsonl(ledger.ledger_dir() / "power.jsonl"),
        tariff=a.tariff, macmon=bool(shutil.which("macmon")), delegations=dels, context=ctx)
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
        note(f"cloud     {tokens(c['tokens'])} ({c['source']})")
    else:
        note(f"cloud     unavailable: {c.get('why')}")
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
    if not L["local"]:
        note("local     no gateway requests in the window")
    dg = L["delegated"]
    outcomes = ", ".join(f"{k} {v}" for k, v in sorted(dg["outcomes"].items())) or "none"
    note(f"delegated {dg['requests']:,} requests inside work, joined on call_id (outcomes: {outcomes})"
         + (f"; {dg['unjoined']['requests']} with no gateway row, not counted" if dg["unjoined"]["requests"] else ""))
    note(f"displaced {local_tokens(L['displaced']['tokens'])} of tagged work served locally")
    if L["mapped"]["tokens"]["requests"]:
        note(f"mapped    {local_tokens(L['mapped']['tokens'])} of untagged history by alias mapping")
        for m in s["mapping"]:
            note(f"          {m['alias']} {m['first_day']}..{m['last_day']} -> {m['purpose']}: {m['why']}")
    e = L["energy"]
    if e.get("available"):
        note(f"energy    {e['kwh']:.2f} kWh, ${e['usd']:,.2f} at ${e['tariff_usd_per_kwh']}/kWh "
             f"(mean {e['mean_watts'] or 0:.0f} W over {e['covered_s'] / 3600:.1f} h covered)")
    else:
        note(f"energy    {e.get('why')}")
    note("")
    note(f"{'day':<10} {'cloud in':>9} {'cloud out':>9} {'cache rd':>9} {'displaced':>9} "
         f"{'eval out':>9} {'unknown out':>11} {'kWh':>6} {'5h peak':>7} {'7d peak':>7}")
    for d in L["days"]:
        loc = d["local"]
        en = d["energy"] or {}
        ct = d["cloud"]["tokens"]
        cell = (lambda k: "n/a" if ct is None else _tok(ct.get(k) or 0))  # noqa: E731
        peaks = ["" if d["headroom"].get(k) is None else f"{d['headroom'][k]:.0f}%" for k in ("five_hour", "seven_day")]
        dt = d["displaced"]["tokens"]
        note(f"{d['day']:<10} {cell('input'):>9} {cell('output'):>9} {cell('cache_read'):>9} "
             f"{_tok(dt['input'] + dt['output']):>9} "
             f"{_tok(loc.get('eval', {}).get('output', 0)):>9} {_tok(loc.get('unknown', {}).get('output', 0)):>11} "
             f"{en.get('kwh', 0):>6.2f} {peaks[0]:>7} {peaks[1]:>7}")
    note("\nClaude Code on a subscription is counted in tokens and plan-window use, not priced (#976)")


def _otel_sum(od: dict) -> dict:
    return {k: sum(d.get(k) or 0 for d in od.values()) for k in ("input", "output", "cache_read", "cache_write")}


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
    cc = ledger.cloud(day)
    root = cr.default_root()
    ctx = cr.scan(cr.transcripts(root, newer_than=start), since=start, until=end) if root.is_dir() else []
    return otel.compare(day, ev, mt, (cc.get("days") or {}).get(day), ctx,
                        ccusage_available=bool(cc.get("available")))


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
