"""`soh cases import|control <source>`: re-run an importer, or its negative control. #603."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, err, note


def cmd_cases(a) -> int:
    from evals import importers
    from evals.core import load_cases
    try:
        mod = importers.module(a.source)
    except ValueError as exc:
        return err(str(exc))
    root = Path(a.out) if a.out else importers.CASES
    if a.action == "import":
        written = importers.run(a.source, root=root)
        note(f"{len(written)} cases from {mod.SOURCE}@{mod.REVISION[:12]} under "
             f"{root / mod.LANE / a.source}")
        emit(bool(written), cases=len(written))
        return 0 if written else 1
    cases = load_cases(root / mod.LANE / a.source)
    got = importers.negative_control(cases, mod.RESPONDERS, mod.passes)
    for name, (passed, total) in got.items():
        note(f"  {name} {passed}/{total}")
    emit(True, control={k: list(v) for k, v in got.items()})
    return 0
