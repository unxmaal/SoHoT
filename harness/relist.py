"""Restart the router once for what it lists with no file or does not list yet (#2018)."""
from __future__ import annotations

from pathlib import Path


def gone(found, where=None) -> list[str]:
    """Advertised ids with no file of that name in the router's dir, which a restart stops listing. #2018."""
    from harness import gguf
    where = Path(where) if where else gguf.models_dir()
    return sorted(i for i in found if not (where / f"{i}.gguf").exists())


def run(found, say=print) -> str:
    """Note the phantoms whose file is gone and relist once, unless one keeps its file; '' when it answered. #2018."""
    from harness import gguf
    dropped = gone(found)
    kept = sorted(set(found) - set(dropped))
    if dropped:
        gguf.note_removed(dropped)
    for name in kept:
        say(f"  {name}: {found[name]}")
    if kept:
        return (f"not restarting: {len(kept)} advertised id(s) keep a file in {gguf.models_dir()}, which a restart "
                f"lists again; `{gguf.REPAIR}` sets auxiliary ones aside")
    removed, unlisted = gguf.removed(), gguf.unlisted()
    why = gguf.relist()
    if not why:
        say(f"relisted: the router restarted for {len(removed)} removed and {len(unlisted)} unlisted"
            if removed or unlisted else "nothing to relist")
    return why
