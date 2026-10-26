"""`soh baseline`: each real workload as all local, all Claude and hybrid, from stored rows. #687."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.commands.common import emit, err, note


def cmd_baseline(a) -> int:
    from evals import workload_baseline as wb
    try:
        if a.save:
            if not a.replay:
                return err("--save writes the summary of a --replay directory; give one")
            recs = wb.summarise(Path(a.replay))
            wb.save(recs, Path(a.save))
            note(f"wrote {len(recs)} records to {Path(a.save).name}")
        got = wb.run(store=a.store or None, summary=a.summary or None, replay=a.replay or None,
                     manifest=a.manifest or None, strata=a.strata or None, lanes=a.lane or wb.LANES,
                     gate=wb.DECIDE_GATE if a.gate is None else a.gate,
                     candidate=a.candidate, bar=a.bar)
    except (wb.Refused, OSError, ValueError, sqlite3.Error) as exc:
        return err(f"baseline refused: {exc}")
    note(wb.text(got))
    emit(True, **got)
    return 0
