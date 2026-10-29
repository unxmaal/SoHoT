"""What metered gateway aliases spend of the prepaid API credit, in dollars, and the api_budget refusal. #1214.

This ledger is apart from gateway_requests and the Max-plan token ledger, so the two are never summed.
"""
from __future__ import annotations

import math
import sqlite3
import sys
import time

from harness import gateway

#: Dollars of API credit the metered aliases may spend since the recorded start; the 2026-10-25 balance. #1214.
BUDGET_USD = 200.0
KNOB = "api_budget"
#: The meta key holding the epoch seconds spend is counted from; absent counts every row.
START_KEY = "api_spend_start"
#: The HTTP status a refused request gets: not retryable, unlike 429 or 503.
REFUSED_STATUS = 402
#: How many callers `soh api-spend` and the morning line name.
TOP_CALLERS = 5
PRICE_KEYS = ("input_cost_per_token", "output_cost_per_token", "cache_read_input_token_cost",
              "cache_creation_input_token_cost")
#: Request tags that name who sent a request; LiteLLM also adds User-Agent tags, which are left out.
CALLER_PREFIXES = ("job:", "purpose:", "run:")
COLUMNS = ("at", "alias", "model", "call_id", "caller", "client", "prompt_tokens", "completion_tokens",
           "cache_read_tokens", "cache_write_tokens", "cost_usd", "cost_source")


def usd(x: float) -> str:
    """Dollars to the cent, or to two significant digits below a cent so a real charge never reads $0.00."""
    x = float(x)
    sign, a = ("-" if x < 0 else ""), abs(x)
    places = 2 if a == 0 or a >= 0.01 else 1 - math.floor(math.log10(a))
    text = f"{a:.{places}f}"
    return sign + "$" + (text if places == 2 else text.rstrip("0"))


def _num(x, kind=float):
    try:
        return kind(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def price(entry) -> dict:
    """The per-token dollars a gateway entry declares, by LiteLLM's own key names."""
    params = (entry or {}).get("litellm_params") or {}
    return {k: float(params[k]) for k in PRICE_KEYS if _num(params.get(k)) is not None}


def metered(entry) -> bool:
    """Whether a request to this entry costs money: a hosted provider's model, or any declared per-token price."""
    if not entry:
        return False
    from harness import nodes
    model = str((entry.get("litellm_params") or {}).get("model") or "")
    hosted = model.startswith(gateway.HOSTED_PROVIDERS) and not entry.get(nodes.NODE_KEY)
    return hosted or any(v > 0 for v in price(entry).values())


def priced(entry) -> bool:
    p = price(entry)
    return "input_cost_per_token" in p and "output_cost_per_token" in p


def config_path(config=None):
    """The config the gateway serves: the generated one beside the base when it exists."""
    base = gateway.config_path(config)
    served = gateway.served_path(base)
    return served if config is None and served.exists() else base


def entry(alias: str, config=None) -> dict | None:
    from harness import models
    return models.entry(alias, config_path(config))


def _usage(response_obj, slo: dict) -> dict:
    usage = getattr(response_obj, "usage", None)
    if usage is None and isinstance(response_obj, dict):
        usage = response_obj.get("usage")
    got = usage if isinstance(usage, dict) else (usage.model_dump() if hasattr(usage, "model_dump") else {})
    meta = (slo.get("metadata") or {}).get("usage_object") or {}
    return {**(meta if isinstance(meta, dict) else {}), **{k: v for k, v in (got or {}).items() if v is not None}}


def cost_of(prompt, completion, cache_read, cache_write, p: dict) -> float | None:
    """Dollars from tokens; LiteLLM's prompt_tokens already counts both kinds of cache token."""
    if prompt is None or completion is None or not priced({"litellm_params": p}):
        return None
    read, write = cache_read or 0, cache_write or 0
    uncached = max(prompt - read - write, 0)
    return (uncached * p["input_cost_per_token"] + completion * p["output_cost_per_token"]
            + read * p.get("cache_read_input_token_cost", p["input_cost_per_token"])
            + write * p.get("cache_creation_input_token_cost", p["input_cost_per_token"]))


def caller_of(tags) -> str:
    named = sorted({str(t).strip() for t in tags or [] if str(t).strip().lower().startswith(CALLER_PREFIXES)})
    return ",".join(named)


def row(kwargs, response_obj, entry_=None) -> dict:
    """One metered request as an api_spend row. Never raises; carries no text."""
    from harness import usage
    kwargs = kwargs if isinstance(kwargs, dict) else {}
    slo = kwargs.get("standard_logging_object") or {}
    slo = slo if isinstance(slo, dict) else {}
    u = _usage(response_obj, slo)
    prompt, completion = _num(slo.get("prompt_tokens"), int), _num(slo.get("completion_tokens"), int)
    read = _num(u.get("cache_read_input_tokens"), int) or 0
    write = _num(u.get("cache_creation_input_tokens"), int) or 0
    cost, source = _num(slo.get("response_cost")), "litellm"
    if not cost:
        cost, source = cost_of(prompt, completion, read, write, price(entry_)), "tokens"
    return {"at": _num(slo.get("startTime")) or time.time(), "alias": str(slo.get("model_group") or ""),
            "model": str(slo.get("model") or ""),
            "call_id": str(slo.get("litellm_call_id") or kwargs.get("litellm_call_id") or "")[:128],
            "caller": caller_of(slo.get("request_tags")), "client": usage.client_of(slo),
            "prompt_tokens": prompt, "completion_tokens": completion, "cache_read_tokens": read,
            "cache_write_tokens": write, "cost_usd": cost, "cost_source": source if cost is not None else ""}


def record(conn, r: dict) -> None:
    conn.execute(f"INSERT INTO api_spend ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                 tuple(r.get(c) for c in COLUMNS))
    conn.commit()


def start(conn) -> float | None:
    got = conn.execute("SELECT value FROM meta WHERE key = ?", (START_KEY,)).fetchone()
    return _num(got[0]) if got else None


def set_start(conn, at: float) -> None:
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (START_KEY, str(float(at))))
    conn.commit()


def spent(conn, since: float | None = None) -> float:
    since = start(conn) if since is None else since
    got = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_spend WHERE at >= ?",
                       (since or 0.0,)).fetchone()
    return float(got[0] or 0.0)


def status(conn, budget: float | None = None) -> dict:
    """Budget, spent, remaining, start and the top callers by dollars."""
    budget = BUDGET_USD if budget is None else float(budget)
    since = start(conn)
    used = spent(conn, since)
    rows = conn.execute(
        "SELECT CASE WHEN caller != '' THEN caller ELSE client END AS who, COUNT(*), SUM(cost_usd), "
        "SUM(prompt_tokens), SUM(completion_tokens) FROM api_spend WHERE at >= ? GROUP BY who "
        "ORDER BY SUM(cost_usd) DESC, who LIMIT ?", (since or 0.0, TOP_CALLERS)).fetchall()
    unpriced = conn.execute("SELECT COUNT(*) FROM api_spend WHERE at >= ? AND cost_usd IS NULL",
                            (since or 0.0,)).fetchone()[0]
    return {"budget": budget, "spent": used, "remaining": budget - used, "start": since,
            "unpriced": int(unpriced),
            "callers": [{"caller": w or "unknown", "requests": n, "cost_usd": c or 0.0,
                         "prompt_tokens": p or 0, "completion_tokens": o or 0} for w, n, c, p, o in rows]}


def line(s: dict) -> str:
    since = time.strftime("%Y-%m-%d", time.localtime(s["start"])) if s.get("start") else "the first row"
    top = s["callers"][0] if s.get("callers") else None
    tail = f"; top caller {top['caller']} {usd(top['cost_usd'])}" if top else ""
    warn = f"; {s['unpriced']} request(s) unpriced" if s.get("unpriced") else ""
    return (f"{usd(s['spent'])} of {usd(s['budget'])} ({KNOB}) since {since}, "
            f"{usd(s['remaining'])} left{tail}{warn}")


def _open():
    """A writable connection to the store this gateway records into; raises when there is none."""
    from harness import memory_store as ms
    from harness import usage
    path = usage.target()
    if path is None:
        raise RuntimeError("the live store is written only by the deploy checkout's gateway")
    return ms.connect(path)


def read_conn():
    """A read-only connection to this checkout's store, or None when it does not exist yet."""
    from harness import ledger
    from harness import memory_store as ms
    path = ms.db_path()
    if not path.exists():
        return None
    conn = ledger.open_ro(path)
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(conn) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'api_spend'").fetchone() is not None


def _tiers(e, config=None) -> list[dict]:
    """A routing arm's metered tier entries, since any request to it may be routed there; [] for any other entry. #1338."""
    from harness import routes
    if not routes.is_router(e):
        return []
    cfg = ((e.get("litellm_params") or {}).get("complexity_router_config") or {}).get("tiers") or {}
    return [t for t in (entry(str(name), config) for name in dict.fromkeys(cfg.values())) if metered(t)]


def _routed(kwargs) -> str:
    md = ((kwargs.get("litellm_params") or {}).get("metadata") or {}) if isinstance(kwargs, dict) else {}
    decision = md.get("routing_decision") if isinstance(md, dict) else None
    return str((decision or {}).get("routed_model") or "") if isinstance(decision, dict) else ""


def gate(alias: str, config=None, budget: float | None = None) -> str:
    """Why a request to `alias` must be refused before it is sent, or ""; a local alias never reads the store."""
    e = entry(alias, config)
    tiers = _tiers(e, config)
    e = tiers[0] if tiers else e
    if not metered(e):
        return ""
    if not priced(e):
        return (f"{alias} is billed per token, but its gateway entry declares no input_cost_per_token and "
                f"output_cost_per_token, so its spend cannot be counted against {KNOB}; declare them (#1214)")
    budget = BUDGET_USD if budget is None else float(budget)
    try:
        conn = _open()
    except Exception as exc:  # noqa: BLE001 - fail closed: no ledger, no metered request
        return f"{alias} is refused: the gateway cannot read its spend ledger ({exc}), so {KNOB} cannot be checked"
    try:
        used = spent(conn)
        if used < budget:
            return ""
        from harness import cuts
        cuts.cut("api_budget", f"{alias} request refused at {usd(used)} spent", value=budget, conn=conn)
    except Exception as exc:  # noqa: BLE001
        return f"{alias} is refused: the gateway cannot read its spend ledger ({exc}), so {KNOB} cannot be checked"
    finally:
        conn.close()
    return (f"{alias} is refused: {usd(used)} of the {usd(budget)} {KNOB} is spent (soh api-spend); "
            f"raise the {KNOB} knob or record a new start with soh api-spend --start DAY (#1214)")


def note(kwargs, response_obj, config=None) -> bool:
    """Record a successful metered request now, so the next gate sees it; False for a local alias."""
    slo = kwargs.get("standard_logging_object") if isinstance(kwargs, dict) else None
    e = entry(str((slo or {}).get("model_group") or ""), config)
    from harness import routes
    if routes.is_router(e):
        e = entry(_routed(kwargs), config)
    if not metered(e):
        return False
    try:
        conn = _open()
        try:
            record(conn, row(kwargs, response_obj, e))
        finally:
            conn.close()
        return True
    except Exception as exc:  # noqa: BLE001 - a lost row is loud, never a failed request
        print(f"api_spend: a metered request's cost was not recorded: {exc}", file=sys.stderr, flush=True)
        return False


def per_case(conn, lane: str, candidate: str = "") -> tuple[float, float] | None:
    """(prompt, completion) tokens per case on `lane` from stored results, the candidate's own first; None unmeasured."""
    if conn is None:
        return None
    sql = ("SELECT AVG(json_extract(x.metrics, '$.prompt_tokens')), "
           "AVG(json_extract(x.metrics, '$.completion_tokens')) FROM results x JOIN runs r ON r.id = x.run_id "
           "WHERE r.lane = ?")
    got = None
    if candidate:
        got = conn.execute(sql + " AND x.candidate = ?", (lane, candidate)).fetchone()
    if not got or got[1] is None:
        got = conn.execute(sql, (lane,)).fetchone()
    if not got or got[1] is None:
        return None
    prompt = got[0]
    if prompt is None:
        alias = gateway.LANE_ALIAS.format(lane)
        prompt = conn.execute("SELECT AVG(prompt_tokens) FROM gateway_requests WHERE alias = ? AND error_class = ''",
                              (alias,)).fetchone()[0]
    return None if prompt is None else (float(prompt), float(got[1]))


def estimate(cases: int, tokens, p: dict) -> float | None:
    """Dollars for `cases` cases at `tokens` (prompt, completion) per case; None when unmeasured."""
    if tokens is None:
        return None
    return cases * cost_of(tokens[0], tokens[1], 0, 0, p)


def check_run(plan: dict, config=None, budget: float | None = None) -> dict | None:
    """The estimate for a run's metered candidates ({candidate: {lane: cases}}) and why it is refused; None if none is metered."""
    metered_ = {c: lanes for c, lanes in plan.items() if metered(entry(c, config))}
    if not metered_:
        return None
    budget = BUDGET_USD if budget is None else float(budget)
    conn = read_conn()
    try:
        used = spent(conn) if conn is not None and _has_table(conn) else 0.0
        each = {(c, lane): estimate(n, per_case(conn, lane, c), price(entry(c, config)))
                for c, lanes in metered_.items() for lane, n in lanes.items() if n}
    finally:
        if conn is not None:
            conn.close()
    total = None if any(v is None for v in each.values()) else sum(each.values())
    remaining = budget - used
    refuse = ""
    if total is not None and total > remaining:
        refuse = (f"the estimate {usd(total)} for {', '.join(sorted(metered_))} on "
                  f"{', '.join(sorted({lane for _, lane in each}))} exceeds the {usd(remaining)} left of the "
                  f"{usd(budget)} {KNOB} (soh api-spend) (#1214)")
    return {"estimate": total, "remaining": remaining, "refuse": refuse,
            "unmeasured": sorted(lane for (_, lane), v in each.items() if v is None)}


def describe(got: dict) -> str:
    est = (f"unknown (no measured tokens per case on {', '.join(got['unmeasured'])})" if got["estimate"] is None
           else f"{usd(got['estimate'])}")
    return f"api spend estimate {est}, {usd(got['remaining'])} left of {KNOB}"
