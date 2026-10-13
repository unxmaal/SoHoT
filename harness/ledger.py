"""`soh ledger`: cloud spend (ccusage), plan headroom (statusline), local use by purpose, displaced dollars, energy. #826."""
from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

from harness import paths, statusline

#: Tier names and the cost-map entry each one prices at.
TIERS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
#: lane -> tier the lane's work stands in for; a lane not named here takes COUNTERFACTUAL_DEFAULT.
COUNTERFACTUAL: dict[str, str] = {}
COUNTERFACTUAL_DEFAULT = "sonnet"
TARIFF_USD_PER_KWH = 0.15
#: Two power samples farther apart than this leave the time between them uncovered.
POWER_GAP_S = 180.0
#: How long one macmon sample averages over, in milliseconds.
POWER_WINDOW_MS = 5000

#: Untagged history known to be one purpose: (alias, first day, last day, purpose, why). A mapping, labelled as one.
ALIAS_PURPOSE = (
    ("eval-7b", "2026-10-08", "2026-10-10", "work", "infovore claims extraction (FINDING #469)"),
    ("Ornith-1.5-35B-Q4_K_M", "2026-10-10", "2026-10-11", "work", "infovore multi-agent review (FINDING #469)"),
)

COST, WORK, UNKNOWN = ("eval", "smoke"), "work", "unknown"
PIN_RE = r'^{name}="([^"]+)"'


def ledger_dir() -> Path:
    return paths.home() / "ledger"


def pin(name: str, path: Path | None = None) -> str:
    """A pin from scripts/versions.sh, '' when absent."""
    path = path or paths.REPO / "scripts" / "versions.sh"
    m = re.search(PIN_RE.format(name=name), Path(path).read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else ""


def day_of(at: float, tz=None) -> str:
    return _dt.datetime.fromtimestamp(at, tz=tz).date().isoformat()


def days_between(since: float, now: float, tz=None) -> list[str]:
    first = _dt.datetime.fromtimestamp(since, tz=tz).date()
    last = _dt.datetime.fromtimestamp(now, tz=tz).date()
    return [(first + _dt.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def day_start(day: str, tz=None) -> float:
    d = _dt.date.fromisoformat(day)
    if tz is None:
        return time.mktime((d.year, d.month, d.day, 0, 0, 0, 0, 0, -1))
    return _dt.datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()


# --- cloud: ccusage -------------------------------------------------------------------------------

def parse_ccusage(doc: dict) -> dict:
    """ccusage daily JSON as {days: {day: {usd, tokens, unpriced}}, unpriced_models}; unpriced cost is never counted."""
    unpriced = sorted((doc.get("totals") or {}).get("unpricedModels") or [])
    days: dict = {}
    for day in doc.get("daily") or []:
        period = day.get("period") or day.get("date")
        if not period:
            continue
        breakdowns = day.get("modelBreakdowns") or []
        tokens = {"input": day.get("inputTokens") or 0, "output": day.get("outputTokens") or 0,
                  "cache_write": day.get("cacheCreationTokens") or 0,
                  "cache_read": day.get("cacheReadTokens") or 0}
        priced, n_priced, unpriced_day = 0.0, 0, {}
        for b in breakdowns:
            name = b.get("modelName")
            if name in unpriced:
                unpriced_day[name] = sum(b.get(k) or 0 for k in (
                    "inputTokens", "outputTokens", "cacheCreationTokens", "cacheReadTokens"))
            else:
                priced += b.get("cost") or 0
                n_priced += 1
        if breakdowns:
            usd = round(priced, 6) if n_priced else None
        else:
            usd = None if unpriced else day.get("totalCost")
        days[period] = {"usd": usd, "tokens": tokens, "unpriced": unpriced_day}
    return {"days": days, "unpriced_models": unpriced}


def ccusage_argv(since_day: str, version: str) -> list[str]:
    return ["npx", "-y", f"ccusage@{version}", "daily", "--json", "--mode", "calculate",
            "--offline", "--since", since_day.replace("-", "")]


def cloud(since_day: str, runner=subprocess.run, which=shutil.which, versions: Path | None = None) -> dict:
    """Claude Code spend from the pinned ccusage; {available: False, why} when it cannot run."""
    version = pin("CCUSAGE_PIN", versions).split("==")[-1]
    out = {"source": f"ccusage@{version}", "mode": "calculate --offline"}
    if not which("npx"):
        return {**out, "available": False, "why": "npx is not on PATH"}
    try:
        proc = runner(ccusage_argv(since_day, version), capture_output=True, text=True, timeout=300)
        doc = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        doc = None
    if not isinstance(doc, dict):
        return {**out, "available": False, "why": "ccusage failed or printed no JSON"}
    return {**out, "available": True, **parse_ccusage(doc)}


# --- plan headroom: the statusline's readings -----------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    got = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("at"), (int, float)):
            got.append(rec)
    return got


def headroom(samples: list[dict], since: float, tz=None) -> dict:
    """The latest reading and each day's peak of the five-hour and seven-day windows."""
    inside = sorted((s for s in samples if s["at"] >= since), key=lambda s: s["at"])
    if not inside:
        return {"available": False, "samples": 0,
                "why": "no statusline readings; install the statusLine wrapper (scripts/statusline.sh)"}
    days: dict = {}
    for s in inside:
        d = days.setdefault(day_of(s["at"], tz), {})
        for w in statusline.WINDOWS:
            if isinstance(s.get(w), (int, float)):
                d[w] = max(d.get(w, 0.0), float(s[w]))
    last = inside[-1]
    latest = {k: last.get(k) for k in ("at", *statusline.WINDOWS,
                                       *(f"{w}_resets_at" for w in statusline.WINDOWS))}
    return {"available": True, "samples": len(inside), "latest": latest, "days": days}


# --- local: gateway_requests by purpose -----------------------------------------------------------

def open_ro(path: Path):
    """The store read-only (SQLite mode=ro): it can neither migrate nor write."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def gateway_rows(conn, since: float) -> list[tuple]:
    """(at, alias, lane, client, purpose, prompt_tokens, completion_tokens, call_id) since `since`."""
    have = _columns(conn, "gateway_requests")
    if not have:
        return []
    purpose = "purpose" if "purpose" in have else f"'{UNKNOWN}'"
    call_id = "call_id" if "call_id" in have else "''"
    return [tuple(r) for r in conn.execute(
        f"SELECT at, alias, lane, client, {purpose}, prompt_tokens, completion_tokens, {call_id} "
        f"FROM gateway_requests WHERE at >= ?", (since,))]


def delegation_rows(conn, since: float) -> list[tuple]:
    """(call_id, at, lane, outcome, prompt_tokens, completion_tokens) of each delegation since `since`; [] before schema 69."""
    if not _columns(conn, "delegations"):
        return []
    return [tuple(r) for r in conn.execute(
        "SELECT call_id, at, lane, outcome, prompt_tokens, completion_tokens FROM delegations WHERE at >= ?",
        (since,))]


def mapped(alias: str, day: str, mapping=None) -> tuple[str, str] | None:
    for a, first, last, purpose, why in (ALIAS_PURPOSE if mapping is None else mapping):
        if a == alias and (not first or day >= first) and (not last or day <= last):
            return purpose, why
    return None


def _bucket():
    return {"requests": 0, "input": 0, "output": 0}


def _add(b: dict, pin_, pout) -> None:
    b["requests"] += 1
    b["input"] += pin_ or 0
    b["output"] += pout or 0


def _day(days: dict, day: str) -> dict:
    return days.setdefault(day, {"purposes": {}, "work_lanes": {}, "mapped": {},
                                 "delegated": {"requests": 0, "outcomes": {}}, "unjoined": _bucket()})


def local(rows: list[tuple], tz=None, mapping=None, delegations=()) -> dict:
    """Per day: tokens by purpose; work by lane; untagged rows a mapping names, kept apart from tagged ones.

    A delegation is counted through its gateway_requests row (joined on call_id), never on its own;
    one with no such row in the window is reported as unjoined and priced nowhere."""
    days: dict = {}
    by_call = {c: (outcome or "pending") for c, _at, _lane, outcome, _i, _o in delegations if c}
    seen = set()
    for at, alias, lane, client, purpose, pin_, pout, *rest in rows:
        call_id = rest[0] if rest else ""
        day = day_of(at, tz)
        d = _day(days, day)
        purpose = purpose or UNKNOWN
        if purpose == UNKNOWN:
            hit = mapped(alias, day, mapping)
            if hit:
                key = f"{alias} -> {hit[0]}: {hit[1]}"
                m = d["mapped"].setdefault(key, {**_bucket(), "purpose": hit[0], "lane": lane or ""})
                _add(m, pin_, pout)
                continue
        _add(d["purposes"].setdefault(purpose, _bucket()), pin_, pout)
        if purpose == WORK:
            _add(d["work_lanes"].setdefault(lane or "", _bucket()), pin_, pout)
        if call_id and call_id in by_call:
            seen.add(call_id)
            d["delegated"]["requests"] += 1
            o = by_call[call_id]
            d["delegated"]["outcomes"][o] = d["delegated"]["outcomes"].get(o, 0) + 1
    for c, at, _lane, _outcome, pin_, pout in delegations:
        if c not in seen:
            _add(_day(days, day_of(at, tz))["unjoined"], pin_, pout)
    return days


# --- displaced dollars: litellm's cost map at the pin ---------------------------------------------

PRICE_PROBE = ("import json, litellm\n"
               "print(json.dumps({k: [v.get('input_cost_per_token'), v.get('output_cost_per_token')]"
               " for k, v in litellm.model_cost.items() if k in %r}))")


def prices(litellm_pin: str, runner=subprocess.run, cache: Path | None = None) -> dict:
    """{model: [usd per input token, usd per output token]} for TIERS, from litellm.model_cost at the pin; cached per pin."""
    cache = cache or ledger_dir() / f"prices-{re.sub(r'[^A-Za-z0-9_.=-]', '_', litellm_pin)}.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            cache.unlink(missing_ok=True)
    argv = ["uv", "run", "--no-project", "--quiet", "--python", "3.12", "--with", litellm_pin,
            "python", "-I", "-c", PRICE_PROBE % (sorted(TIERS.values()),)]
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=600)
        got = json.loads(proc.stdout) if proc.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        got = {}
    if got:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")
    return got


def tier_of(lane: str, override: str = "") -> str:
    return override or COUNTERFACTUAL.get(lane, COUNTERFACTUAL_DEFAULT)


def tier_label(tier: str, table: dict) -> str:
    model = TIERS[tier]
    p = table.get(model)
    if not p or p[0] is None or p[1] is None:
        return f"{tier} ({model}, no price at the pin)"
    return f"{tier} ({model} ${p[0] * 1e6:.2f}/${p[1] * 1e6:.2f} per M in/out)"


def price(bucket: dict, tier: str, table: dict) -> float | None:
    p = table.get(TIERS[tier])
    if not p or p[0] is None or p[1] is None:
        return None
    return round(bucket["input"] * p[0] + bucket["output"] * p[1], 6)


# --- energy: macmon samples -----------------------------------------------------------------------

def macmon_argv() -> list[str]:
    return ["macmon", "pipe", "-s", "1", "-i", str(POWER_WINDOW_MS)]


def watts(sample: dict) -> float | None:
    """macmon's whole-system power, else the SoC's."""
    for key in ("sys_power", "all_power"):
        v = sample.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def sample_power(runner=subprocess.run, which=shutil.which, now=None, path: Path | None = None) -> dict:
    """One macmon reading appended to $LOCALHARNESS_HOME/ledger/power.jsonl."""
    if not which("macmon"):
        return {"ok": False, "why": "macmon is not installed (brew install macmon)"}
    try:
        proc = runner(macmon_argv(), capture_output=True, text=True, timeout=POWER_WINDOW_MS / 1000 + 30)
        line = next((ln for ln in proc.stdout.splitlines() if ln.strip()), "")
        got = json.loads(line) if proc.returncode == 0 and line else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        got = None
    w = watts(got) if isinstance(got, dict) else None
    if w is None:
        return {"ok": False, "why": "macmon printed no power reading"}
    rec = {"at": time.time() if now is None else now, "watts": w,
           **{k: got.get(k) for k in ("cpu_power", "gpu_power", "ane_power", "all_power", "sys_power")}}
    path = path or ledger_dir() / "power.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return {"ok": True, **rec}


def integrate_power(samples: list[dict], max_gap_s: float, tz=None) -> dict:
    """Trapezoid energy over samples no further apart than max_gap_s; kWh in all and per local day."""
    ordered = sorted((s for s in samples if isinstance(s.get("watts"), (int, float))), key=lambda s: s["at"])
    joules, covered, days = 0.0, 0.0, {}
    for a, b in zip(ordered, ordered[1:]):
        dt = b["at"] - a["at"]
        if 0 < dt <= max_gap_s:
            j = (a["watts"] + b["watts"]) / 2 * dt
            joules += j
            covered += dt
            key = day_of((a["at"] + b["at"]) / 2, tz)
            days[key] = days.get(key, 0.0) + j / 3.6e6
    return {"kwh": joules / 3.6e6, "covered_s": covered, "samples": len(ordered),
            "mean_watts": joules / covered if covered else None, "days": days}


def energy(samples: list[dict], since: float, tariff: float, installed: bool, tz=None) -> dict:
    inside = [s for s in samples if s["at"] >= since]
    if not inside:
        why = ("no power samples yet; the energy unit samples macmon every minute" if installed
               else "energy unavailable: macmon is not installed (brew install macmon)")
        return {"available": False, "why": why}
    got = integrate_power(inside, POWER_GAP_S, tz)
    return {"available": True, **got, "tariff_usd_per_kwh": tariff, "usd": round(got["kwh"] * tariff, 6),
            "days": {d: {"kwh": k, "usd": round(k * tariff, 6)} for d, k in got["days"].items()}}


# --- the join -------------------------------------------------------------------------------------

def _sum(buckets) -> dict:
    out = _bucket()
    for b in buckets:
        for k in out:
            out[k] += b[k]
    return out


def build(*, since: float, now: float, cloud_doc: dict, rows: list[tuple], limits: list[dict],
          power: list[dict], table: dict, tier: str = "", tariff: float | None = None,
          macmon: bool = False, litellm_pin: str = "", tz=None, mapping=None, delegations=()) -> dict:
    """The ledger: aggregates only, no prompts, paths or keys."""
    tariff = TARIFF_USD_PER_KWH if tariff is None else tariff
    days = days_between(since, now, tz)
    loc = local(rows, tz, mapping, delegations)
    hr = headroom(limits, since, tz)
    en = energy(power, since, tariff, macmon, tz)
    cdays = cloud_doc.get("days", {}) if cloud_doc.get("available") else {}
    out_days = []
    totals = {"cloud_usd": 0.0, "displaced_usd": 0.0, "mapped_usd": 0.0}
    priced_ok = True
    for day in days:
        c = cdays.get(day, {})
        lday = loc.get(day) or _day({}, day)
        displaced = []
        for lane, b in sorted(lday["work_lanes"].items()):
            t = tier_of(lane, tier)
            usd = price(b, t, table)
            priced_ok &= usd is not None
            displaced.append({"lane": lane, **b, "tier": tier_label(t, table), "usd": usd})
        mapped_rows = []
        for key, b in sorted(lday["mapped"].items()):
            t = tier_of(b["lane"], tier)
            usd = price(b, t, table) if b["purpose"] == WORK else None
            mapped_rows.append({"mapping": key, **b, "tier": tier_label(t, table), "usd": usd})
        d_usd = sum(x["usd"] or 0 for x in displaced)
        m_usd = sum(x["usd"] or 0 for x in mapped_rows)
        totals["cloud_usd"] += c.get("usd") or 0
        totals["displaced_usd"] += d_usd
        totals["mapped_usd"] += m_usd
        e = en.get("days", {}).get(day) if en.get("available") else None
        out_days.append({
            "day": day,
            "cloud": {"usd": c.get("usd"), "tokens": c.get("tokens"), "unpriced": c.get("unpriced", {})},
            "local": lday["purposes"],
            "delegated": lday["delegated"],
            "unjoined_delegations": lday["unjoined"],
            "displaced": {"usd": round(d_usd, 6), "lanes": displaced},
            "mapped": {"usd": round(m_usd, 6), "rows": mapped_rows},
            "cost": {p: lday["purposes"][p] for p in COST if p in lday["purposes"]},
            "unknown": lday["purposes"].get(UNKNOWN),
            "headroom": hr.get("days", {}).get(day, {}) if hr["available"] else {},
            "energy": e,
        })
    purposes: dict = {}
    for d in out_days:
        for p, b in d["local"].items():
            purposes.setdefault(p, []).append(b)
    default_tier = tier or COUNTERFACTUAL_DEFAULT
    return {
        "window": {"since": since, "until": now, "first_day": days[0], "last_day": days[-1]},
        "assumptions": {
            "counterfactual_default": tier_label(default_tier, table),
            "counterfactual_lanes": {lane: tier_label(t, table) for lane, t in sorted(COUNTERFACTUAL.items())}
            if not tier else {},
            "price_source": f"litellm.model_cost at {litellm_pin}",
            "tariff_usd_per_kwh": tariff,
            "mapping": [{"alias": a, "first_day": f, "last_day": l, "purpose": p, "why": w}
                        for a, f, l, p, w in (ALIAS_PURPOSE if mapping is None else mapping)],
        },
        "cloud": {k: v for k, v in cloud_doc.items() if k != "days"}
        | {"usd": round(totals["cloud_usd"], 6) if cloud_doc.get("available") else None},
        "headroom": {k: v for k, v in hr.items() if k != "days"},
        "local": {p: _sum(bs) for p, bs in sorted(purposes.items())},
        "delegated": _delegated(out_days),
        "displaced": {"usd": round(totals["displaced_usd"], 6), "tier": tier_label(default_tier, table),
                      "complete": priced_ok},
        "mapped": {"usd": round(totals["mapped_usd"], 6), "tier": tier_label(default_tier, table),
                   "note": "untagged history assigned by the alias mapping, not by a purpose tag"},
        "energy": {k: v for k, v in en.items() if k != "days"},
        "days": out_days,
    }


def _delegated(days: list[dict]) -> dict:
    outcomes: dict = {}
    for d in days:
        for o, n in d["delegated"]["outcomes"].items():
            outcomes[o] = outcomes.get(o, 0) + n
    return {"requests": sum(d["delegated"]["requests"] for d in days), "outcomes": outcomes,
            "unjoined": _sum(d["unjoined_delegations"] for d in days),
            "note": "delegations are counted inside work through their gateway_requests row (call_id); "
                    "unjoined ones have no such row and are priced nowhere"}


# --- the daily table (schema 70) ------------------------------------------------------------------

def record(conn, ledger: dict, now: float) -> int:
    """Upsert one ledger_days row per day of the window."""
    n = 0
    for d in ledger["days"]:
        conn.execute(
            "INSERT INTO ledger_days (day, recorded_at, cloud_usd, displaced_usd, mapped_usd, tier, "
            "energy_kwh, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET recorded_at=excluded.recorded_at, cloud_usd=excluded.cloud_usd, "
            "displaced_usd=excluded.displaced_usd, mapped_usd=excluded.mapped_usd, tier=excluded.tier, "
            "energy_kwh=excluded.energy_kwh, detail=excluded.detail",
            (d["day"], now, d["cloud"]["usd"], d["displaced"]["usd"], d["mapped"]["usd"],
             ledger["displaced"]["tier"], (d["energy"] or {}).get("kwh"), json.dumps(d, sort_keys=True)))
        n += 1
    conn.commit()
    return n


def recorded(conn, first_day: str) -> list[dict]:
    try:
        rows = conn.execute("SELECT day, recorded_at, cloud_usd, displaced_usd, mapped_usd, tier, energy_kwh "
                            "FROM ledger_days WHERE day >= ? ORDER BY day", (first_day,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]
