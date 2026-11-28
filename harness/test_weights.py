"""A measurement fetches the weights it is about to run and removes them when it ends (#2015)."""
from __future__ import annotations


def fetched(name: str, via: str = "measure") -> str:
    """Fetch what measuring `name` loads and is not on disk, right before its run: why it could not, or "". #2015."""
    from harness import fetching
    from harness import memory_store as ms
    store = ms.connect()
    try:
        return fetching.ensure(store, name, via=via)
    finally:
        store.close()


def refused(name: str, sweep) -> int | None:
    """None once the weights are here; else the run is not launched, said in the sweep or as an error. #2015."""
    from harness.commands.common import err
    missing = fetched(name)
    if not missing:
        return None
    line = f"{name}: not measured: its weights could not be fetched: {missing}"
    if sweep is None:
        return err(line)
    print(f"  {line}", flush=True)
    sweep.lines.append(line)
    return 0


def release(name: str) -> None:
    """The weights of `name` go once its test ends, unless it is adopted, served, pinned or still screened to be measured again. #2015, #2157."""
    from harness import disk
    disk.sweep(names=[name], keep_states=("screened",), say=lambda line: print(f"  {line.strip()}", flush=True))


def release_verdict(vid: int) -> None:
    """release() for the proposal a held verdict names: a confirmation that ended. #2015."""
    from harness import memory_store as ms
    store = ms.connect()
    try:
        row = store.execute("SELECT p.name FROM verdicts v JOIN proposals p ON p.id = v.proposal_id WHERE v.id = ?",
                            (vid,)).fetchone()
    finally:
        store.close()
    if row is not None:
        release(row["name"])
