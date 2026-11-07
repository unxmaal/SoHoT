"""The demand trace `soh residency-sim` replays: gateway requests and queued jobs, each model's resident GB and load seconds (#1559)."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from harness import residency

GB = 1e9
#: Purposes whose requests are batch demand; the rest are a client waiting.
BATCH_PURPOSES = ("eval", "discover")
#: Purposes the harness sends to itself, not demand.
SKIPPED_PURPOSES = ("watchdog", "smoke")
#: Lanes whose served models the pinned+LRU policy holds when no --pin is given (#1558).
PIN_LANES = ("decide", "extract", "code")


def aliases(config=None) -> dict[str, str]:
    """Gateway alias -> the upstream model it serves, provider prefix stripped."""
    from harness import gateway
    out = {}
    for e in gateway.load(config).get("model_list") or []:
        model = ((e or {}).get("litellm_params") or {}).get("model") or ""
        if e.get("model_name") and model:
            out[str(e["model_name"])] = gateway.strip_provider(str(model))
    return out


def model_of(spec: str, alias: dict) -> str:
    """The served model a candidate spec loads, '' for a runner that loads no served text model."""
    s = (spec or "").split(",")[0].strip()
    if s.startswith("llamacpp:"):
        return s[len("llamacpp:"):]
    if s in alias:
        return alias[s]
    return "" if ":" in s else s


def _kv_mlx(path: str) -> int:
    from harness import memory
    try:
        return memory.mlx_kv_bytes_per_token("", path=path)
    except OSError:
        return 0


def sizes(conn, models) -> dict[str, dict]:
    """Model -> weights and resident GB with their source: a GGUF's router plan (file plus planned KV), else file plus one request's KV."""
    from harness import serving
    out = {}
    for m in models:
        stem = m[:-5] if m.endswith(".gguf") else m
        rows = conn.execute(
            "SELECT kind, path, bytes, ctx, kv_bytes_token FROM downloads WHERE (kind = 'gguf' AND (file = ? OR file = ?)) "
            "OR (kind = 'hub' AND repo = ?) ORDER BY removed_at IS NOT NULL, kind = 'hub', bytes = 0, id DESC",
            (f"{stem}.gguf", stem, m)).fetchall()
        for kind, path, size, ctx, kv in rows:
            weights = float(size or 0)
            if not weights and path and Path(path).is_file():
                weights = float(Path(path).stat().st_size)
            if not weights:
                continue
            if kind == "gguf":
                extra, source = float(ctx or 0) * float(kv or 0), "router plan" if ctx and kv else "file"
            else:
                per = _kv_mlx(path)
                extra, source = per * serving.MLX_REQUEST_CTX, "file + 1 request KV" if per else "file"
            out[m] = {"weights_gb": round(weights / GB, 3), "gb": round((weights + extra) / GB, 3), "source": source}
            break
    return out


def measured_loads(logs) -> dict[str, list[float]]:
    """Model -> each cold load's seconds read off the router log (spawn to `model loaded`)."""
    from harness import idle_unload
    got: dict = {}
    for log in logs:
        p = Path(log)
        if p.is_file():
            with p.open(encoding="utf-8", errors="replace") as f:
                for m, v in idle_unload.load_seconds(f).items():
                    got.setdefault(m, []).extend(v)
    return got


def loads(models, measured: dict, weights: dict) -> tuple[dict[str, dict], dict]:
    """Model -> load seconds and source: the router log's median where measured, else the size fit."""
    med = {m: statistics.median(v) for m, v in measured.items() if v}
    fit = residency.fit_rate(med, weights)
    out = {}
    for m in models:
        if m in med:
            out[m] = {"s": round(med[m], 2), "source": f"router log, median of {len(measured[m])}"}
        else:
            out[m] = {"s": round(fit["s_per_gb"] * weights[m], 2),
                      "source": "fallback rate" if fit["fallback"] else "size fit"}
    return out, fit


def requests(conn, since: float, until: float) -> tuple[list[tuple], dict]:
    """(start, end, model, kind) per local gateway request in the window, with counts of what was left out."""
    from harness import gateway
    marks = ", ".join("?" * len(SKIPPED_PURPOSES))
    out, left = [], {"skipped_purpose": 0, "failed": 0, "hosted": 0}
    for at, served, total, purpose, error in conn.execute(
            f"SELECT at, served, total_s, purpose, error_class FROM gateway_requests WHERE at >= ? AND at <= ? "
            f"ORDER BY at", (since, until)):
        if purpose in SKIPPED_PURPOSES:
            left["skipped_purpose"] += 1
        elif error:
            left["failed"] += 1
        elif str(served or "").startswith(gateway.HOSTED_PROVIDERS) or not served:
            left["hosted"] += 1
        else:
            kind = residency.BATCH if purpose in BATCH_PURPOSES else residency.INTERACTIVE
            out.append((float(at), float(at) + float(total or 0), gateway.strip_provider(str(served)), kind))
    return out, left


def jobs(conn, since: float, until: float, alias: dict) -> list[tuple]:
    """(start, end, model, 'job') per candidate a queued job named, over the part of the job inside the window."""
    out = []
    for argv, start, end in conn.execute(
            "SELECT argv, started_at, finished_at FROM jobs WHERE started_at IS NOT NULL AND started_at <= ? "
            "AND COALESCE(finished_at, ?) >= ?", (until, until, since)):
        try:
            args = json.loads(argv or "[]")
        except ValueError:
            continue
        if "--candidates" not in args or args.index("--candidates") + 1 >= len(args):
            continue
        for spec in args[args.index("--candidates") + 1].split(","):
            m = "" if "=" in spec else model_of(spec, alias)
            if m:
                out.append((max(float(start), since), min(float(end or until), until), m, residency.JOB))
    return out


def pins(conn, lanes=PIN_LANES, alias=None) -> tuple[list[str], str]:
    """The served models of the pinned lanes, or none and why."""
    from harness import adopt
    try:
        got = adopt.lane_defaults(conn)
    except Exception as exc:  # noqa: BLE001 - a store with no adoptions still replays, unpinned
        return [], f"lane defaults unreadable: {exc}"
    alias = aliases() if alias is None else alias
    return sorted({model_of(got[ln], alias) for ln in lanes if got.get(ln)} - {""}), ""


def gather(conn, since: float, until: float, logs, alias=None, with_jobs: bool = True) -> dict:
    """Everything one replay needs: the requests of sized models, sizes, load seconds, and what was left out."""
    alias = aliases() if alias is None else alias
    rows, left = requests(conn, since, until)
    held = jobs(conn, since, until, alias) if with_jobs else []
    names = {r[2] for r in rows + held}
    measured = measured_loads(logs)
    every = sizes(conn, sorted(names | set(measured)))
    sized = {m: s for m, s in every.items() if m in names}
    unsized: dict[str, int] = {}
    for r in rows + held:
        if r[2] not in sized:
            unsized[r[2]] = unsized.get(r[2], 0) + 1
    load, fit = loads(sorted(sized), measured, {m: s["weights_gb"] for m, s in every.items()})
    reqs = [residency.Req(*r) for r in rows + held if r[2] in sized]
    return {"window": {"start": since, "end": until}, "reqs": reqs, "sizes": sized, "loads": load, "fit": fit,
            "unsized": unsized, "left_out": left, "jobs": len(held)}
