"""Pending gpu jobs that have waited on memory admission past memory_wait_named: what each needs, what is admissible now, what holds the rest (#1993)."""
from __future__ import annotations

LONG_S = 21600.0


def since(job: dict) -> float | None:
    """When a pending job last became pending: the latest of added, start time, start and finish; None when none is stamped."""
    from harness import workqueue as wq
    got = [wq._epoch(job.get(k)) for k in ("added", "not_before", "started", "finished") if job.get(k)]
    got = [t for t in got if t is not None]
    return max(got) if got else None


def pinned() -> list[tuple[str, float]]:
    """(stem, GiB) of each model the interactive server pins here, once per stem, largest first; [] when it holds none here."""
    from harness import interactive
    if not interactive.reserved_bytes():
        return []
    seen: dict[str, float] = {}
    for entry in interactive.pinned().values():
        stem = str(entry.get("stem") or "")
        if stem:
            seen[stem] = round(float(entry.get("bytes") or 0) / 1024 ** 3, 1)
    return sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))


def holders(conn) -> dict:
    """What holds this machine's memory beside a new load, GiB: the ceiling, reserve, pinned models, Docker VM, live leases, free now."""
    from harness import containers, item_lease, memory, pressure
    leases = item_lease.live(conn)
    p = pressure.sample()
    return {"ceiling": memory.ceiling_gb(), "reserve": memory.measured_reserve_gb(), "pinned_gb": memory.pinned_gb(),
            "pinned": pinned(), "vm": containers.vm_gb(), "free": memory.available_gb(),
            "leased": sum(float(h.get("mem_gb") or 0.0) for h in leases), "leases": len(leases),
            "pressure": "" if not p.alarming else f"memory pressure level {p.level}, not normal"}


def waiting(conn, now: float, record: bool = False) -> list[dict]:
    """This machine's due pending gpu jobs memory admission refuses now that have waited at least LONG_S, longest first; record cuts the shorter waits."""
    from harness import admission, cuts, item_lease
    from harness import workqueue as wq
    jobs = [j for j in wq.pending(conn) if wq.needs(j) == wq.GPU and wq.due(j, now)]
    if not jobs:
        return []
    leases = item_lease.live(conn)
    found = []
    for job in jobs:
        n = admission.need(job)
        if admission.admit(n, leases)[0]:
            continue
        at = since(job)
        waited = now - at if at is not None else 0.0
        if waited < LONG_S:
            if record:
                cuts.cut("memory_wait_named", f"job {job['id']} waited {waited / 3600.0:.1f} h on memory, not yet named",
                         kept=0, dropped=1)
            continue
        found.append((waited, job, n))
    if not found:
        return []
    held = holders(conn)
    room, _ = admission.budget_gb(leases)
    out = []
    for waited, job, n in sorted(found, key=lambda x: (-x[0], x[1]["id"])):
        out.append({"id": job["id"], "title": job.get("title") or "untitled", "waited_s": round(waited),
                    "need_gb": None if n.gb is None else round(n.gb, 1), "priced": n.priced, "resident": n.resident,
                    "unpriced": n.why if n.gb is None else "", "admissible_gb": round(room, 1), **held})
        out[-1]["line"] = line(out[-1])
    return out


def line(w: dict) -> str:
    """One line naming a long memory wait: what it needs, what is admissible now and what holds the rest."""
    if w["need_gb"] is None:
        needs = f"needs an unpriced amount ({w['unpriced']})"
    else:
        parts = ", ".join(f"{s} {g}" for s, g in w["priced"])
        needs = f"needs {w['need_gb']:.1f} GiB" + (f" ({parts})" if parts else "")
    models = ", ".join(f"{s} {g}" for s, g in w["pinned"])
    pins = f"{w['pinned_gb']:.1f} GiB pinned models" + (f" ({models})" if models else "")
    leased = f", {w['leased']:.1f} GiB leased by {w['leases']} running item(s)" if w["leases"] else ""
    pressure = f"; {w['pressure']}" if w["pressure"] else ""
    return (f"job {w['id']} ({w['title']}) has waited {w['waited_s'] / 3600.0:.0f} h and memory does not admit it: {needs}; "
            f"{w['admissible_gb']:.1f} GiB is admissible now ({w['free']:.1f} GiB free); of the {w['ceiling']:.1f} GiB "
            f"ceiling the rest is held by a {w['reserve']:.1f} GiB reserve, {pins}, {w['vm']:.1f} GiB Docker VM"
            f"{leased}{pressure}")
