"""The machines table: this machine's facts and its row."""
from __future__ import annotations

import sqlite3
import json
import time

# Patched names are read through the package, so one patch reaches every caller. #484.
from harness import memory_store as ms


#: The machine this process is running on, resolved once. The probes shell
#: out and the answer does not change while the process runs.
_THIS_MACHINE: dict | None = None


def this_machine() -> dict:
    """The identity facts a verdict needs to stay re-askable.

    IMPORTED LAZILY. evals.environment already computes exactly these for
    receipts and imports harness.memory, so a module-level import here would
    be a cycle -- and writing a second copy is how this repo collected four
    answers to "which engines exist" (RULE #237).

    The fingerprint is machine.fingerprint: hw_model + OS family + arch. Not a
    hostname, which changes without the machine changing, and not the
    interpreter's platform string, which differs between two venvs on one
    machine (#415). The 4070 under Linux and under Windows are different rigs
    by comparable()'s own definition and keep different fingerprints.
    """
    global _THIS_MACHINE
    if _THIS_MACHINE is not None:
        return _THIS_MACHINE
    try:
        from evals import environment
        from harness import inspect as _ins
        from harness import machine as _machine

        env = environment.capture()
        mach = _machine.detect()
        acc = env.get("accelerator") or {}
        got = {
            "hw_model": env.get("hw_model", ""),
            "os": env.get("os", ""),
            "arch": env.get("arch", ""),
            "memory_gb": float(env.get("memory_gb") or 0),
            "accelerator": f"{acc.get('kind', '')} "
                           f"{float(acc.get('total_gb') or 0):.0f}GB".strip(),
            "runtimes": ",".join(sorted(mach.runtimes)),
            "ceiling_gb": _ins.ceiling_bytes() / (1024 ** 3),
            "versions": dict(env.get("versions") or {}),
        }
    except Exception:  # noqa: BLE001
        # A store write must never fail because a probe did. An unknown
        # machine is recorded AS unknown rather than silently attributed to
        # whichever one wrote last, which would be worse than no column.
        got = {"hw_model": "", "os": "", "arch": "", "memory_gb": 0.0,
               "accelerator": "", "runtimes": "", "ceiling_gb": 0.0,
               "versions": {}}
    from harness import machine as _machine
    got["fingerprint"] = _machine.fingerprint(got["hw_model"], got["os"],
                                              got["arch"])
    _THIS_MACHINE = got
    return got


def remember_machine(conn: sqlite3.Connection, facts: dict | None = None) -> int:
    """The id of the row for this machine, inserting or refreshing it."""
    facts = dict(facts or ms.this_machine())
    if not facts.get("fingerprint"):
        from harness import machine as _machine
        facts["fingerprint"] = _machine.fingerprint(
            facts.get("hw_model", ""), facts.get("os", ""), facts.get("arch", ""))
    versions = {k: v for k, v in (facts.get("versions") or {}).items() if v}
    now = time.time()
    # One statement: a SELECT-then-INSERT let two first writers collide. #422.
    conn.execute(
        "INSERT INTO machines (fingerprint, hw_model, os, arch, memory_gb, "
        "accelerator, runtimes, ceiling_gb, first_seen, last_seen, versions) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (fingerprint) DO UPDATE SET "
        "last_seen = excluded.last_seen, runtimes = excluded.runtimes, "
        "ceiling_gb = excluded.ceiling_gb, memory_gb = excluded.memory_gb, "
        "accelerator = excluded.accelerator, os = excluded.os, "
        "versions = excluded.versions",
        (facts["fingerprint"], facts.get("hw_model", ""), facts.get("os", ""),
         facts.get("arch", ""), facts.get("memory_gb", 0.0),
         facts.get("accelerator", ""), facts.get("runtimes", ""),
         facts.get("ceiling_gb", 0.0), now, now,
         json.dumps(versions, sort_keys=True)))
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (facts["fingerprint"],)).fetchone()
    return int(row["id"])


def machine_row(conn, fingerprint: str | None = None) -> int | None:
    """The id stored for a fingerprint (this machine's by default), or None."""
    fp = fingerprint if fingerprint is not None else ms.this_machine()["fingerprint"]
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (fp,)).fetchone()
    return int(row["id"]) if row else None


def recorded_facts(conn, machine_id: int) -> dict:
    """A machines row as until_met's facts, versions decoded. #415."""
    row = conn.execute("SELECT * FROM machines WHERE id = ?",
                       (machine_id,)).fetchone()
    if not row:
        return {}
    got = dict(row)
    try:
        got["versions"] = json.loads(got.get("versions") or "{}")
    except ValueError:
        got["versions"] = {}
    return got
