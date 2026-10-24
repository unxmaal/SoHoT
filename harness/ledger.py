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
#: A reading above this is a stalled counter catching up, not power drawn (vladkens/macmon#76).
POWER_CEILING_W = 480.0
#: A day whose CPU reads 0 W on more than this share of its active samples has energy partial. #1005.
CPU_UNREAD_SHARE = 0.9
#: The first macmon that reads CPU power on macOS 27 without sudo (AppleCLPC counters).
MACMON_CLPC = (0, 9, 0)

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


# --- cloud: which source counts each day (#1160) --------------------------------------------------

#: Transcript usage fields and the ledger's names.
USAGE_KEYS = (("input_tokens", "input"), ("output_tokens", "output"), ("cache_read_input_tokens", "cache_read"),
              ("cache_creation_input_tokens", "cache_write"))
#: Seconds either side of a session's exported requests within which a transcript record counts as exported.
SPAN_SLACK_S = 60.0
LOWER_BOUND = ("transcripts and ccusage miss Claude Code's final usage record for most messages and some requests "
               "entirely (#1160), so a day they count is a lower bound")


def _zero() -> dict:
    return {name: 0 for _, name in TOKEN_KEYS}


def _plus(a: dict, b: dict) -> dict:
    return {k: (a.get(k) or 0) + (b.get(k) or 0) for k in _zero()}


def _stamp(text) -> float | None:
    try:
        t = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)).timestamp()


def usage_messages(files, since: float, until: float | None = None) -> list[dict]:
    """Claude Code usage per API message, once over every file by (message.id, requestId): the final record, else the largest."""
    got: dict = {}
    for path in files:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") if isinstance(rec, dict) else None
                if rec.get("type") != "assistant" or not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                    continue
                at = _stamp(rec.get("timestamp"))
                if at is None or at < since or (until is not None and at >= until):
                    continue
                key = (msg.get("id"), rec.get("requestId")) if msg.get("id") and rec.get("requestId") else rec.get("uuid")
                m = got.setdefault(key, {"at": at, "session": str(rec.get("sessionId") or ""),
                                         "model": str(msg.get("model") or "?"), "final": False, **_zero()})
                final = bool(msg.get("stop_reason"))
                if m["final"] and not final:
                    continue
                for src, name in USAGE_KEYS:
                    n = int(msg["usage"].get(src) or 0)
                    m[name] = n if final and not m["final"] else max(m[name], n)
                m["final"] = m["final"] or final
    return list(got.values())


def spans(events) -> dict:
    """session -> (start, end) its exported api_request events cover, each request's duration included."""
    out: dict = {}
    for e in events:
        if e.get("name") != "api_request" or not e.get("session_id"):
            continue
        lo = e["at"] - (e.get("duration_ms") or 0) / 1000
        a, b = out.get(e["session_id"], (lo, e["at"]))
        out[e["session_id"]] = (min(a, lo), max(b, e["at"]))
    return out


def exported(m: dict, sp: dict, slack: float | None = None) -> bool:
    slack = SPAN_SLACK_S if slack is None else slack
    s = sp.get(m["session"])
    return s is not None and s[0] - slack <= m["at"] <= s[1] + slack


def _by_model(rows, get) -> tuple[dict, dict]:
    total, models = _zero(), {}
    for r in rows:
        t = get(r)
        total = _plus(total, t)
        models[r["model"] or "?"] = _plus(models.get(r["model"] or "?", _zero()), t)
    return total, {k: v for k, v in sorted(models.items()) if any(v.values())}


def _event_tokens(e: dict) -> dict:
    return {"input": int(e.get("input_tokens") or 0), "output": int(e.get("output_tokens") or 0),
            "cache_read": int(e.get("cache_read_tokens") or 0), "cache_write": int(e.get("cache_creation_tokens") or 0)}


def _msg_tokens(m: dict) -> dict:
    return {k: m[k] for k in _zero()}


def gap(events, messages) -> dict:
    """OTel's output against the transcripts' for the same exported requests: the under-count #1160 measures."""
    sp = spans(events)
    api = [e for e in events if e.get("name") == "api_request"]
    mine = [m for m in messages if exported(m, sp)]
    o, t = sum(_event_tokens(e)["output"] for e in api), sum(m["output"] for m in mine)
    return {"otel_requests": len(api), "transcript_messages": len(mine), "otel_output": o, "transcript_output": t,
            "ratio": round(o / t, 2) if t else None}


def cloud_days(days: list[str], cloud_doc: dict, events=(), messages=(), tz=None) -> dict:
    """Per day: Claude Code tokens from OTel where it exported, else transcripts or ccusage as a lower bound."""
    cdays = cloud_doc.get("days", {}) if cloud_doc.get("available") else {}
    sp = spans(events)
    api, msgs = {}, {}
    for e in events:
        if e.get("name") == "api_request":
            api.setdefault(day_of(e["at"], tz), []).append(e)
    for m in messages:
        msgs.setdefault(day_of(m["at"], tz), []).append(m)
    out = {}
    for day in days:
        cc = cdays.get(day)
        tr_total, _ = _by_model(msgs.get(day, ()), _msg_tokens)
        d = {"ccusage": cc["tokens"] if cc else None, "transcripts": tr_total if msgs.get(day) else None,
             "otel": None, "outside": None}
        if api.get(day):
            ot, om = _by_model(api[day], _event_tokens)
            rest = [m for m in msgs.get(day, ()) if not exported(m, sp)]
            rt, rm = _by_model(rest, _msg_tokens)
            models = {k: _plus(om.get(k, _zero()), rm.get(k, _zero())) for k in sorted(set(om) | set(rm))}
            d.update(tokens=_plus(ot, rt), models=models, otel=ot, outside=rt if rest else None,
                     source="otel+transcripts" if rest else "otel", lower_bound=bool(rest), outside_messages=len(rest))
        elif cc:
            d.update(tokens=cc["tokens"], models=cc["models"], source="ccusage", lower_bound=True)
        elif msgs.get(day):
            d.update(tokens=tr_total, models=_by_model(msgs[day], _msg_tokens)[1], source="transcripts",
                     lower_bound=True)
        else:
            d.update(tokens=None, models={}, source=None, lower_bound=False)
        out[day] = d
    return out


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
    """macmon's whole-system power, else the SoC's; 0 W is a reading, a missing field is not. #1005."""
    got = [float(v) for v in (sample.get(k) for k in ("sys_power", "all_power"))
           if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0]
    return next((v for v in got if v > 0), got[0] if got else None)


def macmon_version(runner=subprocess.run, which=shutil.which) -> str | None:
    """The installed macmon's version, None when it is absent or says nothing."""
    if not which("macmon"):
        return None
    try:
        out = runner(["macmon", "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return m.group(0) if m else None


def sample_power(runner=subprocess.run, which=shutil.which, now=None, path: Path | None = None) -> dict:
    """One macmon reading appended to $LOCALHARNESS_HOME/ledger/power.jsonl."""
    if not which("macmon"):
        return {"ok": False, "why": "macmon is not installed (brew install macmon)"}
    try:
        proc = runner(macmon_argv(), capture_output=True, text=True, timeout=POWER_WINDOW_MS / 1000 + 30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "why": f"macmon did not run: {type(e).__name__}"}
    if proc.returncode != 0:
        return {"ok": False, "why": f"macmon exited {proc.returncode}"}
    line = next((ln for ln in proc.stdout.splitlines() if ln.strip()), "")
    try:
        got = json.loads(line) if line else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return {"ok": False, "why": "macmon printed no JSON"}
    w = watts(got)
    if w is None:
        return {"ok": False, "why": "macmon JSON has no sys_power or all_power"}
    rec = {"at": time.time() if now is None else now, "watts": w,
           **{k: got.get(k) for k in ("cpu_power", "gpu_power", "ane_power", "all_power", "sys_power",
                                      "ram_power", "cpu_active_ratio", "gpu_active_ratio")}}
    path = path or ledger_dir() / "power.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return {"ok": True, **rec}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _plausible(s: dict, ceiling: float) -> bool:
    return _num(s.get("watts")) and 0 <= s["watts"] <= ceiling


def without_cpu(s: dict) -> dict:
    """The sample less its CPU figure: what is left when the CPU channel is not a reading."""
    cpu = s.get("cpu_power") if _num(s.get("cpu_power")) else 0.0
    return {**s, "watts": max(0.0, s["watts"] - cpu)}


def integrate_power(samples: list[dict], max_gap_s: float, tz=None, ceiling: float | None = None) -> dict:
    """Trapezoid energy over samples no further apart than max_gap_s; kWh in all and per local day."""
    ceiling = POWER_CEILING_W if ceiling is None else ceiling
    ordered = sorted((s for s in samples if _plausible(s, ceiling)), key=lambda s: s["at"])
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


def cpu_unread(samples: list[dict], tz=None) -> dict:
    """{day: (CPU 0 W while active, samples with a CPU figure)}; no recorded ratio counts as active. #1005."""
    out: dict = {}
    for s in samples:
        if not _num(s.get("cpu_power")):
            continue
        d = out.setdefault(day_of(s["at"], tz), [0, 0])
        d[1] += 1
        if s["cpu_power"] == 0 and s.get("cpu_active_ratio") != 0:
            d[0] += 1
    return {d: tuple(v) for d, v in out.items()}


def is_partial(zero: int, counted: int, share: float | None = None) -> bool:
    share = CPU_UNREAD_SHARE if share is None else share
    return counted > 0 and zero / counted > share


def _older(version: str | None, than: tuple) -> bool | None:
    if not version:
        return None
    return tuple(int(x) for x in version.split(".")) < than


def partial_why(zero: int, counted: int, version: str | None) -> str:
    head = f"CPU read 0 W on {zero} of {counted} samples with the CPU active, so the CPU is not counted"
    old = _older(version, MACMON_CLPC)
    if old is False:
        return f"{head}; macmon {version} still reads no CPU power on this machine"
    who = f"macmon {version}" if version else "macmon before 0.9.0"
    return (f"{head}; {who} reads the IOReport CPU Energy channel that macOS 27 stalls, and 0.9.0 and later "
            "read the AppleCLPC counters without sudo (vladkens/macmon#76; brew has 0.8.2, so install --HEAD)")


def _scope(samples: list[dict]) -> str | None:
    both = [s for s in samples if _num(s.get("sys_power")) and _num(s.get("all_power"))]
    if not both:
        return None
    return "system" if any(s["sys_power"] > s["all_power"] + 0.01 for s in both) else "soc"


def energy(samples: list[dict], since: float, tariff: float, installed: bool, tz=None,
           macmon_version: str | None = None) -> dict:
    inside = [s for s in samples if s["at"] >= since]
    if not inside:
        why = ("no power samples yet; the energy unit samples macmon every minute" if installed
               else "energy unavailable: macmon is not installed (brew install macmon)")
        return {"available": False, "why": why}
    got = integrate_power(inside, POWER_GAP_S, tz)
    rest = integrate_power([without_cpu(s) for s in inside if _num(s.get("watts"))], POWER_GAP_S, tz)
    unread = cpu_unread(inside, tz)
    days, lower, zero, counted = {}, 0.0, 0, 0
    for d, k in got["days"].items():
        z, n = unread.get(d, (0, 0))
        if is_partial(z, n):
            lb = rest["days"].get(d, 0.0)
            days[d] = {"kwh": None, "usd": None, "partial": True, "lower_bound_kwh": lb,
                       "why": partial_why(z, n, macmon_version)}
            zero, counted = zero + z, counted + n
        else:
            lb = k
            days[d] = {"kwh": k, "usd": round(k * tariff, 6)}
        lower += lb
    partial = any(v.get("partial") for v in days.values())
    out = {"available": True, **got, "tariff_usd_per_kwh": tariff, "usd": round(got["kwh"] * tariff, 6),
           "partial": partial, "implausible": sum(1 for s in inside if _num(s.get("watts"))
                                                  and not _plausible(s, POWER_CEILING_W)),
           "ceiling_w": POWER_CEILING_W, "scope": _scope(inside), "macmon": macmon_version, "days": days}
    if partial:
        out.update(kwh=None, usd=None, mean_watts=None, lower_bound_kwh=lower,
                   why=partial_why(zero, counted, macmon_version))
    return out


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


def cloud_summary(cloud_doc: dict, cdays: list[dict], available: bool) -> dict:
    """The window's Claude Code tokens, the days each source counted, and ccusage's own total as the cross-check."""
    sources: dict = {}
    for c in cdays:
        if c["source"]:
            sources[c["source"]] = sources.get(c["source"], 0) + 1
    cc = {k: v for k, v in cloud_doc.items() if k != "days"}
    cc["tokens"] = _cloud_sum({"tokens": c["ccusage"]} for c in cdays) if cloud_doc.get("available") else None
    lower = any(c["lower_bound"] for c in cdays)
    return {"available": available, "tokens": _cloud_sum(cdays) if available else None, "sources": sources,
            "lower_bound": lower, "why": None if available else cloud_doc.get("why"),
            "note": LOWER_BOUND if lower else None, "ccusage": cc}


def build(*, since: float, now: float, cloud_doc: dict, rows: list[tuple], limits: list[dict],
          power: list[dict], tariff: float | None = None, macmon: bool = False, tz=None, mapping=None,
          delegations=(), context=(), macmon_version: str | None = None, census_doc: dict | None = None,
          events=(), messages=()) -> dict:
    """The ledger: aggregates only, no prompts, paths or keys; Claude usage in tokens, never dollars (#976)."""
    tariff = TARIFF_USD_PER_KWH if tariff is None else tariff
    days = days_between(since, now, tz)
    loc = local(rows, tz, mapping, delegations)
    hr = headroom(limits, since, tz)
    en = energy(power, since, tariff, macmon, tz, macmon_version)
    cdays = cloud_days(days, cloud_doc, events, messages, tz)
    available = any(c["tokens"] is not None for c in cdays.values())
    ctx = context_days(context, tz)
    out_days = []
    for day in days:
        c = cdays[day]
        lday = loc.get(day) or _day({}, day)
        displaced = [{"lane": lane, **b} for lane, b in sorted(lday["work_lanes"].items())]
        mapped_rows = [{"mapping": key, **b} for key, b in sorted(lday["mapped"].items())]
        e = en.get("days", {}).get(day) if en.get("available") else None
        out_days.append({
            "day": day,
            "cloud": c,
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
        "cloud": cloud_summary(cloud_doc, [d["cloud"] for d in out_days], available),
        "headroom": {k: v for k, v in hr.items() if k != "days"},
        "local": {p: _sum(bs) for p, bs in sorted(purposes.items())},
        "delegated": _delegated(out_days),
        "accepted": accepted(delegations, days, census_doc, tz),
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


#: The #1151 census shapes of cloud subtasks a lane's delegation could have served instead.
LANE_SHAPES = {"code": ("small_code_edit",), "extract": ("extract_classify", "summarise_digest"),
               "decide": ("triage_decide",), "svg": ("media",)}


def census_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "evals" / "analysis" / "demand"


def census(where: Path | None = None) -> dict:
    """Cloud subtasks per day by shape, weighted back from the #1151 census manifest; unavailable without one."""
    where = census_dir() if where is None else Path(where)
    try:
        frame = json.loads((where / "strata.json").read_text(encoding="utf-8"))
        rows = [json.loads(ln) for ln in (where / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
                if ln.strip()]
        days = float(frame["days"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"available": False, "why": f"no #1151 census at {where.name} ({type(exc).__name__})"}
    per: dict = {}
    for r in rows:
        shape = ((r.get("final") or {}).get("shape")) or ""
        if shape:
            per[shape] = per.get(shape, 0.0) + float(r.get("weight") or 1.0)
    return {"available": True, "days": days, "now": frame.get("now"),
            "per_day": {k: round(v / days, 3) for k, v in sorted(per.items())}}


def accepted(delegations, days: list[str], cen: dict | None = None, tz=None) -> dict:
    """Per lane: accepted local tasks per day and in all, against cloud subtasks of the same census shape. #1158."""
    from harness import delegations as dl
    lanes: dict = {}
    for _c, at, lane, outcome, _i, _o in delegations:
        b = lanes.setdefault(lane or "", {k: 0 for k in dl.KINDS} | {"days": {}})
        k = dl.kind(outcome)
        b[k] += 1
        if k == dl.ACCEPTED:
            day = day_of(at, tz)
            b["days"][day] = b["days"].get(day, 0) + 1
    cen = cen or {"available": False, "why": "no census given"}
    for lane, b in lanes.items():
        b["per_day"] = round(b[dl.ACCEPTED] / max(1, len(days)), 3)
        shapes = LANE_SHAPES.get(lane, ())
        b["shapes"] = list(shapes)
        cloud = sum(cen["per_day"].get(s, 0.0) for s in shapes) if cen.get("available") and shapes else None
        b["cloud_per_day"] = None if cloud is None else round(cloud, 3)
        b["local_share"] = (None if cloud is None or b["per_day"] + cloud == 0
                            else round(b["per_day"] / (b["per_day"] + cloud), 4))
    total = {k: sum(b[k] for b in lanes.values()) for k in dl.KINDS}
    closed = total[dl.ACCEPTED] + total[dl.REJECTED]
    return {"lanes": dict(sorted(lanes.items())), "total": total,
            "accepted_share": round(total[dl.ACCEPTED] / closed, 4) if closed else None,
            "census": {k: v for k, v in cen.items() if k != "per_day"}}


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
