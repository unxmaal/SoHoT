"""The interactive server: a llama-server holding each LAN lane's model pinned, apart from the eval router. #1561."""
from __future__ import annotations

import json
import os
import struct
import sys
import time
from pathlib import Path

from harness import serving

#: Lanes whose model the interactive server pins, in the order its budget is spent.
LANES = ("decide", "extract", "code")
PORT = 8083
PORT_ENV = "INTERACTIVE_PORT"
URL_ENV = "INTERACTIVE_URL"
BUDGET_GB = 25.0
#: Slots a pinned model gets when its lane has no request history here.
SLOTS = 2
#: The most tokens of KV a pinned model's unified pool may hold, and its size with no request history.
POOL_CTX = 32768
#: Days of a lane's gateway requests its pinned slots and pool are sized from.
DEMAND_DAYS = 30
#: llama-server's compute buffers beside one model's weights and KV.
COMPUTE_BYTES = 512 * 1024 ** 2
#: Gateway entry key: the MLX model a GGUF entry stands in for on this server.
STANDS_IN_KEY = "interactive_for"
PLAN_NAME = "interactive.json"
MODELS_NAME = "interactive-models"
WARM_WAIT_S = 600.0
WARM_POLL_S = 2.0
GIB = 1024 ** 3


def url() -> str:
    """Where the interactive server listens: INTERACTIVE_URL (another machine), else this one's port."""
    got = (os.environ.get(URL_ENV) or "").strip()
    if got:
        return serving.bare(got)
    port = (os.environ.get(PORT_ENV) or "").strip()
    return f"http://127.0.0.1:{port if port.isdigit() else PORT}"


def plan_path() -> Path:
    from harness import paths
    return paths.home() / PLAN_NAME


def _gib(n: float) -> str:
    return f"{n / GIB:.1f}"


def stem_for(spec: str, config=None, stand_in: bool = True) -> str:
    """The GGUF stem a lane spec is served as by llama-server; an MLX id maps to the entry standing in for it."""
    from harness import gateway
    name = (spec or "").partition(",")[0].strip()
    if name.startswith(serving.LLAMACPP_PREFIX):
        return name[len(serving.LLAMACPP_PREFIX):].strip()
    if not name or ":" in name:
        return ""
    for entry in gateway.load(config).get("model_list") or []:
        named = str(entry.get("model_name", "")).strip().lower() == name.lower()
        stands = stand_in and str(entry.get(STANDS_IN_KEY, "")).strip().lower() == name.lower()
        source = str(entry.get("source_file") or "")
        if (named or stands) and source.endswith(".gguf"):
            return source[:-len(".gguf")]
    return ""


def demand(conn, lane: str, names, now: float | None = None) -> dict:
    """A lane's interactive requests over DEMAND_DAYS: count, p99 and max of prompt plus reply tokens, peak overlap."""
    from harness import purpose, usage
    names = sorted({n for n in names if n})
    since = (time.time() if now is None else now) - DEMAND_DAYS * 86400
    rows = conn.execute(
        "SELECT at, total_s, COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0) FROM gateway_requests "
        f"WHERE at >= ? AND purpose NOT IN (?, ?, ?) AND (alias = ? OR (client = ? AND lane = ?)"
        f"{' OR alias IN (' + ','.join('?' * len(names)) + ')' if names else ''})",
        (since, purpose.EVAL, purpose.SMOKE, purpose.WATCHDOG, f"sohot-{lane}", usage.DIRECT_CLIENT, lane,
         *names)).fetchall()
    tokens = sorted(int(r[2]) for r in rows if r[2])
    edges = sorted([(float(r[0]), 1) for r in rows if r[1]] + [(float(r[0]) + float(r[1]), -1) for r in rows if r[1]])
    peak = now_in = 0
    for _, step in edges:
        now_in += step
        peak = max(peak, now_in)
    return {"n": len(rows), "p99": tokens[int(0.99 * (len(tokens) - 1))] if tokens else 0,
            "max": tokens[-1] if tokens else 0, "peak": peak}


def shape(got: dict | None, trained: int) -> tuple[int, int, int]:
    """(slots, pool tokens, tokens the history asks for): its peak overlap, room for its largest request and p99 per slot."""
    from harness import context
    if not got or not got.get("n"):
        return SLOTS, min(POOL_CTX, trained), 0
    slots = max(int(got["peak"]), 1)
    want = max(int(got["max"]), int(got["p99"]) * slots, context.FLOOR)
    stepped = -(-want // context.STEP) * context.STEP
    return slots, min(stepped, POOL_CTX, trained), want


def size(stem: str, models_dir, got: dict | None = None) -> dict | None:
    """Weights plus a pool shaped by the lane's request history plus compute buffers for one GGUF; None when unreadable."""
    from harness import context
    path = Path(models_dir) / f"{stem}.gguf"
    try:
        meta, weights = context.read_meta(path), path.stat().st_size
    except (OSError, ValueError, KeyError, struct.error):
        return None
    per, full = context.kv_bytes_per_token(meta), context.trained(meta)
    if not per or not full:
        return None
    slots, ctx, want = shape(got, full)
    kv = per * ctx + context.swa_bytes(meta) * slots
    return {"stem": stem, "path": str(path), "ctx": ctx, "trained": full, "want": want, "slots": slots,
            "demand": got or {}, "weights": weights, "kv": kv, "bytes": weights + kv + COMPUTE_BYTES}


def choose(defaults: dict, typed: dict, config=None, models_dir=None, budget_gb: float | None = None,
           sized=size, record: bool = False, demands: dict | None = None) -> dict:
    """Each pinned lane's model inside the budget: the lane's own, else its typed default; what did not fit, said."""
    budget = int((BUDGET_GB if budget_gb is None else budget_gb) * GIB)
    left, lanes, skipped = budget, {}, {}
    for lane in LANES:
        tried = []
        for spec in dict.fromkeys(s for s in (defaults.get(lane), typed.get(lane)) if s):
            stem = stem_for(spec, config)
            if not stem:
                tried.append(f"{spec} has no GGUF build")
                continue
            shared = next((p for p in lanes.values() if p["stem"] == stem), None)
            got = dict(shared, bytes=0) if shared else sized(stem, models_dir, (demands or {}).get(lane))
            if got is None:
                tried.append(f"{stem}.gguf is not readable in {models_dir}")
                continue
            if got["bytes"] > left:
                tried.append(f"{stem} needs {_gib(got['bytes'])} GiB with {_gib(left)} of {_gib(budget)} GiB left")
                if record:
                    from harness import cuts
                    cuts.cut("interactive_budget_gb", f"{lane}: {tried[-1]}", kept=0, dropped=1)
                continue
            _, _, opts = spec.partition(",")
            lanes[lane] = {**got, "spec": spec,
                           "served": serving.LLAMACPP_PREFIX + stem + (f",{opts}" if opts else ""),
                           "why": "the lane's model" if spec == defaults.get(lane) else
                                  f"its typed default ({'; '.join(tried)})"}
            left -= got["bytes"]
            break
        else:
            skipped[lane] = "; ".join(tried) or "the lane serves nothing"
    return {"url": url(), "budget_bytes": budget, "bytes": budget - left, "lanes": lanes, "skipped": skipped,
            "at": time.time()}


def plan_now(conn=None, config=None, record: bool = False) -> dict:
    """choose() for this machine's lane models, GGUF dir and each pinned lane's request history now."""
    from harness import adopt, gguf, runs, winners
    typed = winners.typed()
    with runs.store(conn) as c:
        defaults = adopt.lane_defaults(c, typed=typed)
        demands = {lane: demand(c, lane, {_alias(s) for s in (defaults.get(lane), typed.get(lane))}) for lane in LANES}
    return choose(defaults, typed, config, gguf.models_dir(), record=record, demands=demands)


def _alias(spec) -> str:
    """The gateway name a lane spec is asked for by: a llamacpp: stem bare."""
    name = str(spec or "").partition(",")[0].strip()
    return name[len(serving.LLAMACPP_PREFIX):] if name.startswith(serving.LLAMACPP_PREFIX) else name


def read() -> dict:
    """The plan the running server was started with; {} when none was written."""
    try:
        got = json.loads(plan_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def write(plan: dict) -> Path:
    path = plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def clear() -> None:
    plan_path().unlink(missing_ok=True)


def pinned() -> dict:
    """lane -> pinned entry, from the running server's plan."""
    return dict(read().get("lanes") or {})


def reserved_bytes() -> int:
    """What the pinned set holds of this machine's memory for good; 0 when it runs elsewhere or not at all."""
    plan = read()
    if not plan.get("lanes") or not serving.loopback(str(plan.get("url") or "")):
        return 0
    return int(plan.get("bytes") or 0)


def params(entry: dict, base: str = "") -> dict:
    """A gateway alias's litellm_params for a pinned entry."""
    return {"model": f"openai/{entry['stem']}", "api_base": f"{serving.bare(base or read().get('url') or url())}/v1",
            "api_key": "not-needed"}


def holds(lane: str, get=None) -> dict | None:
    """The pinned entry for `lane` when the interactive server says its model is resident, else None."""
    from harness import router
    plan = read()
    entry = (plan.get("lanes") or {}).get(lane)
    if not entry:
        return None
    base = serving.bare(str(plan.get("url") or url()))
    got = router.statuses(get, base=base)
    if not got or got.get(entry["stem"]) not in router.RESIDENT:
        return None
    return {**entry, "url": base}


def route(lane: str, get=None) -> tuple[str, serving.Route] | None:
    """(served spec, Route) on the interactive server for a lane it holds, else None."""
    held = holds(lane, get)
    if not held:
        return None
    spec = held["served"]
    _, _, opts = spec.partition(",")
    return spec, serving.Route(held["url"], held["stem"], serving._sampling(opts, spec),
                               serving.template_options(opts, spec))


def upstream(where) -> tuple[str, str] | None:
    """(base, stem) when `where` is a pinned model on the interactive server, else None."""
    if where is None:
        return None
    plan = read()
    base = serving.bare(str(plan.get("url") or ""))
    if not base or serving.bare(where.base) != base:
        return None
    stems = {p["stem"] for p in (plan.get("lanes") or {}).values()}
    return (base, where.model) if where.model in stems else None


def served_ctx(stem: str) -> int | None:
    """The tokens one request may reach on the interactive server: the whole unified pool."""
    for entry in pinned().values():
        if entry["stem"] == stem:
            return int(entry["ctx"])
    return None


def eval_pair(conn, defaults=None, models_dir=None, k: int | None = None, config=None) -> tuple[int, list[str]]:
    """The k heaviest router models a lane serves, at their floor context: what an eval must still fit."""
    from harness import adopt, context, gguf
    defaults = adopt.lane_defaults(conn) if defaults is None else defaults
    models_dir = Path(gguf.models_dir() if models_dir is None else models_dir)
    k = context.recorded_models_max() if k is None else k
    held = {}
    for spec in defaults.values():
        stem = stem_for(spec, config, stand_in=False)
        path = models_dir / f"{stem}.gguf"
        if not stem or stem in held:
            continue
        try:
            meta, weights = context.read_meta(path), path.stat().st_size
        except (OSError, ValueError, KeyError, struct.error):
            continue
        held[stem] = weights + context.kv_bytes_per_token(meta) * context.FLOOR + context.swa_bytes(meta)
    top = sorted(held.items(), key=lambda kv: kv[1], reverse=True)[:max(k, 1)]
    return sum(b for _, b in top), [f"{s} {_gib(b)}" for s, b in top]


def check(plan: dict, budget: int, beside: int, pair: tuple[int, list[str]]) -> tuple[bool, str]:
    """Whether the pinned set fits beside the co-resident MLX model and the largest eval pair, naming every number."""
    pinned_set = ", ".join(f"{lane} {p['stem']} {_gib(p['bytes'])}" for lane, p in (plan.get("lanes") or {}).items())
    need = int(plan.get("bytes") or 0) + beside + pair[0]
    said = (f"the pinned set {_gib(plan.get('bytes') or 0)} GiB ({pinned_set or 'nothing'}) + "
            f"{_gib(beside)} GiB of MLX beside it + the largest eval pair {_gib(pair[0])} GiB "
            f"({', '.join(pair[1]) or 'none'}) = {_gib(need)} GiB")
    if need > budget:
        return False, f"refused: {said}, over the {_gib(budget)} GiB budget by {_gib(need - budget)} GiB"
    return True, f"fits: {said} of the {_gib(budget)} GiB budget, {_gib(budget - need)} GiB to spare"


def check_here(plan: dict, conn=None) -> tuple[bool, str]:
    """check() against this machine's budget, MLX co-resident and lane models."""
    from harness import context
    from harness import memory_store as ms
    own = conn is None
    conn = ms.connect() if own else conn
    try:
        return check(plan, context.budget_bytes(conn), context.coresident_bytes(conn), eval_pair(conn))
    finally:
        if own:
            conn.close()


def drift(plan: dict, fresh: dict) -> dict:
    """lane -> [running stem, stem it would pin now] for every lane that changed."""
    old = {lane: p["stem"] for lane, p in (plan.get("lanes") or {}).items()}
    new = {lane: p["stem"] for lane, p in (fresh.get("lanes") or {}).items()}
    return {lane: [old.get(lane, ""), new.get(lane, "")] for lane in sorted(set(old) | set(new))
            if old.get(lane) != new.get(lane)}


def health(plan: dict | None = None, get=None) -> dict:
    """Whether the server is up with every pinned model resident; planned False when nothing is pinned here."""
    from harness import router
    plan = read() if plan is None else plan
    stems = sorted({p["stem"] for p in (plan.get("lanes") or {}).values()})
    if not stems:
        return {"planned": False}
    base = serving.bare(str(plan.get("url") or url()))
    got = router.statuses(get, base=base)
    return {"planned": True, "url": base, "up": got is not None, "pinned": stems,
            "missing": [s for s in stems if (got or {}).get(s) not in router.RESIDENT]}


#: What the watchdog's interactive_down criterion catches; its action restarts the unit, never stops it. #1561.
WHAT = "the interactive server is down, a pinned model is not loaded, or a pinned lane's model changed"


def watch(loaded) -> dict:
    """health() plus drift for the watchdog; {} when no interactive unit is loaded here."""
    if not loaded:
        return {}
    got = health()
    if got.get("planned"):
        try:
            got["drift"] = drift(read(), plan_now())
        except Exception as exc:  # noqa: BLE001 - an unreadable store leaves drift unknown, never a restart
            got["drift_unknown"] = f"{type(exc).__name__}: {exc}"[:300]
    return got


def finding(w) -> list:
    """The watchdog's interactive_down finding when the server is down, missing a pinned model or drifted."""
    from harness.watchdog import Finding, Subject
    got = w.interactive or {}
    if not got.get("planned") or (got["up"] and not got["missing"] and not got.get("drift")):
        return []
    return [Finding("interactive_down", Subject("server", "interactive", "the launchd interactive unit is loaded",
                                                detail={"service": "interactive"}),
                    {k: got.get(k) for k in ("up", "missing", "drift")})]


def load(stems, base: str, post=None) -> list[str]:
    """Ask the server to load each stem; the ones it took."""
    from harness import router
    done = []
    for stem in stems:
        try:
            (post or (lambda p, b: router._post(p, b, base)))("/models/load", {"model": stem})
        except Exception as exc:  # noqa: BLE001 - one refused load leaves the rest to try
            print(f"interactive: {stem} did not load: {exc}", file=sys.stderr)
            continue
        done.append(stem)
    return done


def warm(plan: dict | None, wait_s: float, get=None, post=None, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Load every pinned model once the server answers, then re-point the gateway if its aliases predate the plan."""
    plan = read() if plan is None else plan
    end = clock() + wait_s
    got = health(plan, get)
    while got.get("planned") and not got["up"] and clock() < end:
        sleep(WARM_POLL_S)
        got = health(plan, get)
    if got.get("planned") and not got["up"]:
        from harness import cuts
        cuts.cut("interactive_warm_wait", "the interactive server did not answer; its pinned models were not loaded",
                 kept=0, dropped=len(got["pinned"]))
    if got.get("planned") and got["up"] and got["missing"]:
        load(got["missing"], got["url"], post)
    if got.get("planned") and stale_gateway(plan):
        from harness import gateway
        gateway.refresh_gateway()
    return got


def stale_gateway(plan: dict, config=None) -> bool:
    """Whether the served gateway config sends a pinned lane's alias anywhere but its pinned model."""
    import yaml

    from harness import gateway
    path = gateway.served_path(config)
    try:
        served = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return False
    by_name = {str(e.get("model_name", "")): e.get("litellm_params") or {} for e in served.get("model_list") or []}
    for lane, entry in (plan.get("lanes") or {}).items():
        want = params(entry, str(plan.get("url") or ""))
        got = by_name.get(gateway.LANE_ALIAS.format(lane)) or {}
        if (got.get("api_base"), got.get("model")) != (want["api_base"], want["model"]):
            return True
    return False


def preset(out: Path, plan: dict) -> Path:
    """Write the server's preset and a models dir holding only the pinned files; the dir."""
    from harness import context, paths
    out = Path(out)
    stems = {p["stem"]: p for p in (plan.get("lanes") or {}).values()}
    rows = [{"stem": s, "ctx": p["ctx"], "slots": p["slots"], "why": f"pinned, {_gib(p['bytes'])} GiB"}
            for s, p in stems.items()]
    capped = sorted(s for s, p in stems.items() if int(p.get("want") or 0) > int(p["ctx"]))
    if capped:
        from harness import cuts
        cuts.cut("interactive_pool_ctx", f"pinned pools smaller than their lanes' measured requests: {', '.join(capped)}",
                 dropped=len(capped))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(context.preset_text(rows, POOL_CTX, SLOTS), encoding="utf-8")
    context.models_max_path(out).write_text(f"{max(len(stems), 1)}\n", encoding="utf-8")
    models = paths.home() / MODELS_NAME
    models.mkdir(parents=True, exist_ok=True)
    for link in models.glob("*.gguf"):
        if link.name[:-len(".gguf")] not in stems:
            link.unlink()
    for stem, p in stems.items():
        link = models / f"{stem}.gguf"
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(p["path"])
    return models


def main(argv=None) -> int:
    """`python -m harness.interactive plan|check|serve PRESET|warm|health`."""
    argv = sys.argv[1:] if argv is None else argv
    what = argv[0] if argv else ""
    if what == "plan":
        print(json.dumps(plan_now(), indent=1, sort_keys=True))
        return 0
    if what in ("check", "serve"):
        plan = plan_now(record=True)
        ok, why = check_here(plan)
        print(f"interactive: {why}", file=sys.stderr)
        for lane, skip in plan["skipped"].items():
            print(f"interactive: {lane} is not pinned: {skip}", file=sys.stderr)
        if not ok:
            clear()
            return 1
        write(plan)
        if what == "serve":
            if len(argv) != 2:
                print("usage: python -m harness.interactive serve PRESET.ini", file=sys.stderr)
                return 2
            print(preset(Path(argv[1]), plan) if plan["lanes"] else "")
        return 0
    if what == "warm":
        print(json.dumps(warm(None, WARM_WAIT_S), sort_keys=True), file=sys.stderr)
        return 0
    if what == "health":
        got = health()
        print(json.dumps(got, sort_keys=True))
        return 0 if not got.get("planned") or (got["up"] and not got["missing"]) else 1
    print("usage: python -m harness.interactive plan|check|serve PRESET|warm|health", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
