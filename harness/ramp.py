"""Allocate in steps until macOS first pushes back. See README, #299."""
from __future__ import annotations

import json
import time

from harness import pressure as pr


def _mlx():
    import mlx.core as mx

    held: list = []

    def allocate(gb: float) -> None:
        # Random data: zeros would compress and never reach the GPU wiring
        # that a model load does.
        a = mx.random.uniform(shape=(int(gb * 2 ** 30 / 4),))
        mx.eval(a)
        held.append(a)

    def release() -> None:
        held.clear()
        mx.clear_cache()

    return allocate, release


def run(step_gb: float = 1.0, settle_s: float = 3.0, floor_pct: int = 10,
        cap_gb: float | None = None, allocate=None, release=None, sample=None,
        sleep=time.sleep, available=None) -> dict:
    """Grow GPU-resident memory until the first sign of pressure, then free it."""
    from harness import memory
    if allocate is None or release is None:
        allocate, release = _mlx()
    sample = sample or pr.sample
    available = available or memory.available_gb
    if cap_gb is None:
        total = memory._unified_total_gb() or memory.system_memory_gb()
        if total <= 0:
            raise ValueError("this machine's memory size is unknown, so there "
                             "is no safe cap; pass cap_gb")
        cap_gb = total - 4

    def row(gb):
        p = sample()
        return {"gb": gb, "free_pct": p.free_pct, "level": p.level,
                "swapouts": p.swapouts, "wired_gb": p.wired_gb,
                "available_gb": round(available(), 2)}

    base = row(0)
    steps, held, stopped, warn_at = [], 0.0, "cap", None
    try:
        while held + step_gb <= cap_gb:
            try:
                allocate(step_gb)
            except Exception as exc:  # noqa: BLE001
                stopped = f"allocation failed: {str(exc)[:160]}"
                break
            held += step_gb
            sleep(settle_s)
            now = row(held)
            steps.append(now)
            why = _stop(now, base, floor_pct)
            if why:
                stopped, warn_at = why, held
                break
    finally:
        release()
    last_normal = (warn_at - step_gb) if warn_at is not None else held
    margin = (round(base["available_gb"] - last_normal, 2)
              if warn_at is not None else None)
    return {"margin_gb": margin,"step_gb": step_gb, "floor_pct": floor_pct, "cap_gb": cap_gb,
            "baseline": base, "steps": steps, "stopped": stopped,
            "warn_at_gb": warn_at, "last_normal_gb": last_normal,
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _stop(now: dict, base: dict, floor_pct: int) -> str:
    if (now["level"] or 0) >= pr.WARN:
        return "pressure warn"
    if (now["swapouts"] is not None and base["swapouts"] is not None
            and now["swapouts"] > base["swapouts"]):
        return "compressor swapping"
    if now["free_pct"] is not None and now["free_pct"] <= floor_pct:
        return "free below floor"
    return ""


#: Runs kept per machine; the guard reads the worst of them.
KEEP = 10


def _epoch(stamp) -> float:
    try:
        return time.mktime(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return time.time()


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def save(conn, report: dict, machine_id: int) -> int:
    """One ramp result as a memory_limits row for that machine. #415."""
    cur = conn.execute(
        "INSERT INTO memory_limits (machine_id, measured_at, margin_gb, "
        "last_normal_gb, stopped, report) VALUES (?,?,?,?,?,?)",
        (machine_id, _epoch(report.get("measured_at")),
         _num(report.get("margin_gb")), _num(report.get("last_normal_gb")),
         str(report.get("stopped") or ""), json.dumps(report, sort_keys=True)))
    conn.commit()
    return cur.lastrowid


def runs(conn, machine_id: int | None) -> list[dict]:
    """A machine's newest KEEP ramp results, oldest first."""
    if machine_id is None:
        return []
    got = conn.execute(
        "SELECT report FROM memory_limits WHERE machine_id = ? "
        "ORDER BY measured_at DESC, id DESC LIMIT ?",
        (machine_id, KEEP)).fetchall()
    out = []
    for r in reversed(got):
        try:
            out.append(json.loads(r["report"]))
        except ValueError:
            continue
    return out
