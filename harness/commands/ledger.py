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
    from harness import context_report as cr, ledger, memory_store as ms, store

    since = cr.parse_when(a.since, now)
    first_day = ledger.days_between(since, now)[0]
    start = ledger.day_start(first_day)
    rows, dels, history = [], [], []
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
        finally:
            conn.close()
    pin = ledger.pin("LITELLM_PIN")
    out = ledger.build(
        since=start, now=now, cloud_doc=ledger.cloud(first_day), rows=rows,
        limits=ledger.read_jsonl(ledger.ledger_dir() / "ratelimits.jsonl"),
        power=ledger.read_jsonl(ledger.ledger_dir() / "power.jsonl"),
        table=ledger.prices(pin), tier=a.tier, tariff=a.tariff,
        macmon=bool(shutil.which("macmon")), litellm_pin=pin, delegations=dels)
    out["recorded"] = history
    return out


def show(L: dict) -> None:
    w, s = L["window"], L["assumptions"]
    note(f"ledger {w['first_day']} .. {w['last_day']}")
    c = L["cloud"]
    if c.get("available"):
        unpriced = ", ".join(c.get("unpriced_models") or []) or "none"
        note(f"cloud     {_usd(c['usd'])} Claude Code API-equivalent ({c['source']}); "
             f"unpriced, not counted: {unpriced}")
    else:
        note(f"cloud     unavailable: {c.get('why')}")
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


def cmd_ledger(a) -> int:
    from harness import ledger

    now = time.time()
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
