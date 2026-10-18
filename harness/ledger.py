"""`soh ledger`: Claude Code tokens (ccusage), plan headroom (statusline), local use by purpose, displaced tokens, energy. #826, #976."""
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

#: ccusage's token fields and the ledger's names; a Max-plan login pays no per-token price, so none is read. #976.
TOKEN_KEYS = (("inputTokens", "input"), ("outputTokens", "output"), ("cacheReadTokens", "cache_read"),
              ("cacheCreationTokens", "cache_write"))


def _tokens(rec: dict) -> dict:
    return {name: int(rec.get(key) or 0) for key, name in TOKEN_KEYS}


def parse_ccusage(doc: dict) -> dict:
    """ccusage daily JSON as {days: {day: {tokens, models: {model: tokens}}}}."""
    days: dict = {}
    for day in doc.get("daily") or []:
        period = day.get("period") or day.get("date")
        if not period:
            continue
        models = {b.get("modelName") or "?": _tokens(b) for b in day.get("modelBreakdowns") or []}
        days[period] = {"tokens": _tokens(day), "models": models}
    return {"days": days}


def ccusage_argv(since_day: str, version: str) -> list[str]:
    return ["npx", "-y", f"ccusage@{version}", "daily", "--json", "--mode", "calculate",
            "--offline", "--since", since_day.replace("-", "")]


def cloud(since_day: str, runner=subprocess.run, which=shutil.which, versions: Path | None = None) -> dict:
    """Claude Code tokens per day from the pinned ccusage; {available: False, why} when it cannot run."""
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
    one with no such row in the window is reported as unjoined and counted nowhere."""
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


def _cloud_sum(days) -> dict:
    out = {name: 0 for _, name in TOKEN_KEYS}
    for d in days:
        for k in out:
            out[k] += (d.get("tokens") or {}).get(k) or 0
    return out


def build(*, since: float, now: float, cloud_doc: dict, rows: list[tuple], limits: list[dict],
          power: list[dict], tariff: float | None = None, macmon: bool = False, tz=None, mapping=None,
          delegations=(), context=()) -> dict:
    """The ledger: aggregates only, no prompts, paths or keys; Claude usage in tokens, never dollars (#976)."""
    tariff = TARIFF_USD_PER_KWH if tariff is None else tariff
    days = days_between(since, now, tz)
    loc = local(rows, tz, mapping, delegations)
    hr = headroom(limits, since, tz)
    en = energy(power, since, tariff, macmon, tz)
    available = bool(cloud_doc.get("available"))
    cdays = cloud_doc.get("days", {}) if available else {}
    ctx = context_days(context, tz)
    out_days = []
    for day in days:
        c = cdays.get(day)
        lday = loc.get(day) or _day({}, day)
        displaced = [{"lane": lane, **b} for lane, b in sorted(lday["work_lanes"].items())]
        mapped_rows = [{"mapping": key, **b} for key, b in sorted(lday["mapped"].items())]
        e = en.get("days", {}).get(day) if en.get("available") else None
        out_days.append({
            "day": day,
            "cloud": {"tokens": c["tokens"] if c else None, "models": c["models"] if c else {}},
            "context": ctx.get(day, {}),
            "local": lday["purposes"],
            "delegated": lday["delegated"],
            "unjoined_delegations": lday["unjoined"],
            "displaced": {"tokens": _sum(displaced), "lanes": displaced},
            "mapped": {"tokens": _sum(m for m in mapped_rows if m["purpose"] == WORK), "rows": mapped_rows},
            "cost": {p: lday["purposes"][p] for p in COST if p in lday["purposes"]},
            "unknown": lday["purposes"].get(UNKNOWN),
            "headroom": hr.get("days", {}).get(day, {}) if hr["available"] else {},
            "energy": e,
        })
    purposes: dict = {}
    for d in out_days:
        for p, b in d["local"].items():
            purposes.setdefault(p, []).append(b)
    return {
        "window": {"since": since, "until": now, "first_day": days[0], "last_day": days[-1]},
        "assumptions": {
            "tariff_usd_per_kwh": tariff,
            "mapping": [{"alias": a, "first_day": f, "last_day": l, "purpose": p, "why": w}
                        for a, f, l, p, w in (ALIAS_PURPOSE if mapping is None else mapping)],
        },
        "cloud": {k: v for k, v in cloud_doc.items() if k != "days"}
        | {"tokens": _cloud_sum(d["cloud"] for d in out_days) if available else None},
        "headroom": {k: v for k, v in hr.items() if k != "days"},
        "local": {p: _sum(bs) for p, bs in sorted(purposes.items())},
        "delegated": _delegated(out_days),
        "displaced": {"tokens": _sum(d["displaced"]["tokens"] for d in out_days),
                      "note": "tagged work served locally, in tokens"},
        "mapped": {"tokens": _sum(d["mapped"]["tokens"] for d in out_days),
                   "note": "untagged history assigned by the alias mapping, not by a purpose tag"},
        "energy": {k: v for k, v in en.items() if k != "days"},
        "days": out_days,
    }


def context_days(rows, tz=None) -> dict:
    """{day: {tool: tokens}} of tool results entering Claude's context (#828 rows), by local day. #827."""
    out: dict = {}
    for r in rows or ():
        if r.get("at") is None:
            continue
        d = out.setdefault(day_of(r["at"], tz), {})
        d[r["tool"]] = d.get(r["tool"], 0) + (r.get("tokens") or 0)
    return out


def _delegated(days: list[dict]) -> dict:
    outcomes: dict = {}
    for d in days:
        for o, n in d["delegated"]["outcomes"].items():
            outcomes[o] = outcomes.get(o, 0) + n
    return {"requests": sum(d["delegated"]["requests"] for d in days), "outcomes": outcomes,
            "unjoined": _sum(d["unjoined_delegations"] for d in days),
            "note": "delegations are counted inside work through their gateway_requests row (call_id); "
                    "unjoined ones have no such row and are counted nowhere"}


# --- the daily table (schema 70, dollar columns dropped in 77) -----------------------------------

def record(conn, ledger: dict, now: float) -> int:
    """Upsert one ledger_days row per day of the window."""
    n = 0
    for d in ledger["days"]:
        conn.execute(
            "INSERT INTO ledger_days (day, recorded_at, energy_kwh, detail) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET recorded_at=excluded.recorded_at, energy_kwh=excluded.energy_kwh, "
            "detail=excluded.detail",
            (d["day"], now, (d["energy"] or {}).get("kwh"), json.dumps(d, sort_keys=True)))
        n += 1
    conn.commit()
    return n


def recorded(conn, first_day: str) -> list[dict]:
    """Each recorded day with its Claude tokens, read from the detail."""
    try:
        rows = conn.execute("SELECT day, recorded_at, energy_kwh, detail FROM ledger_days WHERE day >= ? "
                            "ORDER BY day", (first_day,)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        try:
            detail = json.loads(r["detail"] or "{}")
        except ValueError:
            detail = {}
        out.append({"day": r["day"], "recorded_at": r["recorded_at"], "energy_kwh": r["energy_kwh"],
                    "cloud_tokens": (detail.get("cloud") or {}).get("tokens")})
    return out
