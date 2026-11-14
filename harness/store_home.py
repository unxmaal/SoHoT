"""The one home that works this store on each machine; another home's worker is refused (#1935)."""
from __future__ import annotations

from pathlib import Path

#: meta key prefix, then the machines row id: the home whose worker works this store on that machine.
KEY = "store_home:"


def _home(home=None) -> str:
    from harness import paths
    return str(Path(home or paths.home()).resolve())


def claimed(conn, mid) -> str | None:
    """The home that works this store on machine `mid`, or None before any worker claimed it."""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (f"{KEY}{mid}",)).fetchone()
    return None if row is None else row["value"]


def refused(conn, home=None) -> str:
    """Why this home's worker may not work this store, or '' once this home holds the machine's claim."""
    from harness import memory_store as ms, monitor
    here, mid = _home(home), ms.remember_machine(conn)
    key = f"{KEY}{mid}"
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, here))
    held = claimed(conn, mid)
    if held != here and (monitor.live_home(Path(here)) or not Path(held).is_dir()):
        conn.execute("UPDATE meta SET value = ? WHERE key = ? AND value = ?", (here, key, held))
        held = claimed(conn, mid)
    conn.commit()
    if held == here:
        return ""
    return (f"refused: {held} works this store on this machine, and its running jobs' pid files are not under "
            f"{here}, so this worker would take them for dead; run the worker from {held}")
