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
#: (monotonic time, answer) for an incomplete identity, reused until machine.RETRY_S passes. #747.
_PROVISIONAL: tuple[float, dict] | None = None


def _now() -> float:
    return time.monotonic()


def this_machine() -> dict:
    """The identity facts a verdict needs to stay re-askable.

    IMPORTED LAZILY. evals.environment already computes exactly these for
    receipts and imports harness.memory, so a module-level import here would
    be a cycle -- and writing a second copy is how this repo collected four
    answers to "which engines exist" (RULE #237).

    The fingerprint is machine.fingerprint: hw_model + OS family + arch + host
    id (#697). Not a hostname, which changes without the machine changing, and not the
    interpreter's platform string, which differs between two venvs on one
    machine (#415). The 4070 under Linux and under Windows are different rigs
    by comparable()'s own definition and keep different fingerprints.
    """
    global _THIS_MACHINE, _PROVISIONAL
    if _THIS_MACHINE is not None:
        return _THIS_MACHINE
    from harness import machine as _machine
    if _PROVISIONAL is not None and _now() - _PROVISIONAL[0] < _machine.RETRY_S:
        return _PROVISIONAL[1]
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
            "host": env.get("host", ""),
            "memory_gb": float(env.get("memory_gb") or 0),
            "accelerator": f"{acc.get('kind', '')} "
                           f"{float(acc.get('total_gb') or 0):.0f}GB".strip(),
            "runtimes": ",".join(sorted(mach.runtimes)),
            "ceiling_gb": _ins.ceiling_bytes() / (1024 ** 3),
            "versions": dict(env.get("versions") or {}),
        }
    except Exception:  # noqa: BLE001
        # A store write must never fail because a probe did; partial facts never overwrite a stored row. #747.
        got = {"hw_model": "", "os": "", "arch": "", "host": "", "memory_gb": 0.0,
               "accelerator": "", "runtimes": "", "ceiling_gb": 0.0,
               "versions": {}, **_identity(), "partial": True}
        # A failed probe is not this machine for the rest of the process: ask again next time. #747.
        complete = False
    else:
        # A host read back after a failed uuid probe is not yet this machine's answer. #747.
        complete = not _machine.uuid_failed()
    got["fingerprint"] = _machine.fingerprint(got["hw_model"], got["os"],
                                              got["arch"], got["host"])
    if complete:
        _THIS_MACHINE, _PROVISIONAL = got, None
    else:
        _PROVISIONAL = (_now(), got)
    return got


#: This machine's fingerprint from the cheap identity probes, for a process that only looks its row up. #1427.
_THIS_FINGERPRINT: str | None = None


def this_fingerprint() -> str:
    """this_machine()'s fingerprint without the runtime-version probes it takes to fill the rest. #1427."""
    global _THIS_FINGERPRINT
    # A stand-in this_machine names the machine for every caller, this one too. #451.
    if _THIS_MACHINE is not None or getattr(ms.this_machine, "__module__", "") != __name__:
        return ms.this_machine()["fingerprint"]
    if _THIS_FINGERPRINT is not None:
        return _THIS_FINGERPRINT
    from harness import machine as _machine
    try:
        from evals import environment
        fp = environment.identity()["fingerprint"]
    except Exception:  # noqa: BLE001
        return ms.this_machine()["fingerprint"]
    if not fp or _machine.uuid_failed():
        # A host from a failed uuid probe is not this machine's answer yet. #747.
        return ms.this_machine()["fingerprint"]
    _THIS_FINGERPRINT = fp
    return fp


def _identity() -> dict:
    """hw_model, os, arch and host from the cheap probes, or {} when they fail too. #747."""
    try:
        from evals import environment
        me = environment.identity()
    except Exception:  # noqa: BLE001
        return {}
    return {k: me.get(k) or "" for k in ("hw_model", "os", "arch", "host")}


def remember_machine(conn: sqlite3.Connection, facts: dict | None = None) -> int:
    """The id of the row for this machine, inserting or refreshing it."""
    facts = dict(facts or ms.this_machine())
    if not facts.get("fingerprint"):
        from harness import machine as _machine
        facts["fingerprint"] = _machine.fingerprint(
            facts.get("hw_model", ""), facts.get("os", ""), facts.get("arch", ""),
            facts.get("host", ""))
    _claim(conn, facts["fingerprint"])
    versions = {k: v for k, v in (facts.get("versions") or {}).items() if v}
    now = time.time()
    # Facts from a failed capture refresh only last_seen, never the row's measured facts. #747.
    refresh = ("last_seen = excluded.last_seen" if facts.get("partial") else
               "last_seen = excluded.last_seen, runtimes = excluded.runtimes, "
               "ceiling_gb = excluded.ceiling_gb, memory_gb = excluded.memory_gb, "
               "accelerator = excluded.accelerator, os = excluded.os, "
               "versions = excluded.versions")
    # One statement: a SELECT-then-INSERT let two first writers collide. #422.
    conn.execute(
        "INSERT INTO machines (fingerprint, hw_model, os, arch, memory_gb, "
        "accelerator, runtimes, ceiling_gb, first_seen, last_seen, versions) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (fingerprint) DO UPDATE SET "
        + refresh,
        (facts["fingerprint"], facts.get("hw_model", ""), facts.get("os", ""),
         facts.get("arch", ""), facts.get("memory_gb", 0.0),
         facts.get("accelerator", ""), facts.get("runtimes", ""),
         facts.get("ceiling_gb", 0.0), now, now,
         json.dumps(versions, sort_keys=True)))
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (facts["fingerprint"],)).fetchone()
    return int(row["id"])


def _machine_of(fp: str) -> dict:
    from harness import machine as _machine
    return _machine.parse_fingerprint(fp)


def _claim(conn, fp: str) -> None:
    """This host takes over its board's row from before hosts were recorded, once. #697."""
    # Only the store's own host: another host's receipt must not inherit this one's history.
    if not _machine_of(fp) or fp != ms.this_machine()["fingerprint"]:
        return
    if conn.execute("SELECT 1 FROM machines WHERE fingerprint = ?", (fp,)).fetchone():
        return
    conn.execute("UPDATE machines SET fingerprint = ? WHERE fingerprint = ?",
                 (fp, fp.rsplit("/", 1)[0]))


def machine_row(conn, fingerprint: str | None = None) -> int | None:
    """The id stored for a fingerprint (this machine's by default), or None."""
    fp = fingerprint if fingerprint is not None else ms.this_fingerprint()
    row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                       (fp,)).fetchone()
    if row is None and fingerprint is None and _machine_of(fp):
        # Read only: the row from before hosts, until remember_machine claims it. #697.
        row = conn.execute("SELECT id FROM machines WHERE fingerprint = ?",
                           (fp.rsplit("/", 1)[0],)).fetchone()
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
