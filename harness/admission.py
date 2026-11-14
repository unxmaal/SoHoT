"""Admission before load: a gpu item is leased only when its models are resident or fit beside the live leases and pinned set. #1558."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Need:
    """What a queued item's models need, GiB; None when nothing prices it."""
    gb: float | None
    priced: list = field(default_factory=list)
    resident: list = field(default_factory=list)
    why: str = ""


def _gguf_gb(stem: str) -> float | None:
    """A router stem's weights plus its recorded KV, GiB; None when the file is not here."""
    from harness import context, gguf
    path = gguf.models_dir() / f"{stem}.gguf"
    try:
        weights, meta = path.stat().st_size, context.read_meta(path)
    except (OSError, ValueError, KeyError):
        return None
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        row = context.served(conn, stem)
    finally:
        conn.close()
    ctx = int(row["ctx"]) if row and row.get("ctx") else 0
    return (weights + context.kv_bytes_per_token(meta) * ctx) / 1024 ** 3


def spec_gb(spec: str) -> float | None:
    """GiB loading one local candidate costs: a measured peak, else weights (plus KV) on disk; None when unknown."""
    from harness import memory
    if spec.startswith("llamacpp:"):
        return _gguf_gb(spec.partition(":")[2])
    got = memory.need_gb(spec.partition(":")[2] if ":" in spec else spec, spec=spec)
    return got if isinstance(got, float) else None


def local_specs(job: dict) -> list[str] | None:
    """The candidates a queued eval loads on this machine; None for a job that names none."""
    from evals import run
    args = run.queued_args(job.get("argv") or [])
    if args is None or not getattr(args, "candidates", ""):
        return None
    return [c for c in run.split_candidates(args.candidates) if not run.hosted(c)]


def model_id(spec: str) -> str:
    """The model a server holds for a candidate spec: a router stem or an mlx repo, options and method dropped."""
    from harness import methods
    base = (methods.base_of(spec) or spec).partition(",")[0].strip()
    return base.partition(":")[2] if ":" in base else base


def waiting(conn=None) -> set[str]:
    """Models the ready gpu jobs here name, which no release should unload from under them. #1617."""
    from harness import workqueue as wq
    out = set()
    for job in wq.ready(conn):
        if wq.needs(job) == wq.GPU:
            out.update(model_id(s) for s in local_specs(job) or [])
    return out


def need(job: dict, resident=None) -> Need:
    """What a queued job's models need; an eval prices each local candidate, a model already resident costs nothing."""
    local = local_specs(job)
    if local is None:
        return Need(None, why="not an eval with named candidates, so unpriced")
    held = set(resident() if resident else _resident())
    out = Need(0.0)
    for spec in local:
        if model_id(spec) in held or spec in held:
            out.resident.append(spec)
            continue
        gb = spec_gb(spec)
        if gb is None:
            return Need(None, out.priced, out.resident, f"{spec} has no size here, so unpriced")
        out.priced.append((spec, round(gb, 1)))
        out.gb += gb
    return out


def _resident() -> list[str]:
    from harness import router
    try:
        return router.resident()
    except Exception:  # noqa: BLE001 - a router that cannot be asked holds nothing we can count on
        return []


def budget_gb(held: list[dict]) -> tuple[float, str]:
    """GiB a new load may take now: the least of what is free and what the ledger of live leases leaves."""
    from harness import memory
    reserve, pinned = memory.measured_reserve_gb(), memory.held_gb()
    leased = sum(float(h.get("mem_gb") or 0.0) for h in held)
    free = memory.budget_gb(memory.available_gb(), memory.ceiling_gb() - pinned, 0.0, reserve)
    ledger = memory.ceiling_gb() - pinned - reserve - leased
    return min(free, ledger), (f"{free:.1f} GiB free after a {reserve:.1f} GiB reserve and {pinned:.1f} GiB held "
                               f"by pinned models and the Docker VM; "
                               f"{ledger:.1f} GiB left by the ledger after {leased:.1f} GiB leased")


def never(n: Need) -> str:
    """Why a need can never be admitted here, even with no lease held: over the ceiling less the reserve and held set; '' when it may fit later. #1926."""
    from harness import memory
    if not n.gb:
        return ""
    ceiling = memory.ceiling_gb()
    reserve, held = memory.measured_reserve_gb(), memory.held_gb()
    most = ceiling - reserve - held
    if ceiling <= 0 or n.gb <= most + 1e-9:
        return ""
    return (f"needs {n.gb:.1f} GiB ({', '.join(f'{s} {g}' for s, g in n.priced)}) but at most {most:.1f} GiB is ever "
            f"admissible here: a {ceiling:.1f} GiB ceiling less a {reserve:.1f} GiB reserve and {held:.1f} GiB held by "
            f"pinned models and the Docker VM. Run it on another node, or with a smaller quant, or after stopping what "
            f"holds the {held:.1f} GiB; a harness limit, never the model's")


def admit(n: Need, held: list[dict], sample=None) -> tuple[bool, str]:
    """(admitted, why): normal pressure, and a need that is unknown, resident or inside the budget."""
    from harness import pressure
    p = (sample or pressure.sample)()
    if p.alarming:
        return False, f"memory pressure level {p.level}, not normal"
    if n.gb is None:
        return True, f"admitted unchecked: {n.why}"
    if n.gb == 0.0:
        return True, f"its models are resident: {', '.join(n.resident)}" if n.resident else "it loads nothing here"
    room, how = budget_gb(held)
    if n.gb > room:
        return False, (f"needs {n.gb:.1f} GiB ({', '.join(f'{s} {g}' for s, g in n.priced)}) but {room:.1f} GiB is "
                       f"admissible: {how}; a harness limit, never the model's")
    return True, f"{n.gb:.1f} GiB into {room:.1f} GiB"
