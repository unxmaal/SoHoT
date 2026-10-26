"""`soh blame sample|report|codebook`: the #918 blame audit of terminal verdicts, on the store read-only."""
from __future__ import annotations

from pathlib import Path

from harness.commands.common import emit, err, note

#: Where the committed queue, key and label files live.
DIR = Path(__file__).resolve().parents[2] / "evals" / "blame"


def _open(path: str):
    from harness import live_audit, memory_store as ms
    db = Path(path) if path else ms.db_path()
    if not db.is_file():
        raise FileNotFoundError(f"no store at {db}")
    return live_audit.open_readonly(db)


def cmd_blame(a) -> int:
    import sqlite3

    from harness import blame_audit as ba
    out = Path(a.dir) if a.dir else DIR
    if a.action == "codebook":
        note(ba.codebook_text())
        emit(True, codebook=ba.CODEBOOK, rules=list(ba.RULES), evidence=ba.EVIDENCE)
        return 0
    try:
        after = ba.since(a.since) if getattr(a, "since", "") else None
    except ValueError as exc:
        return err(f"blame: {exc}")
    try:
        conn = _open(a.db)
    except (OSError, sqlite3.Error) as exc:
        return err(f"blame: {exc}")
    try:
        if a.action == "sample":
            got = ba.build(conn, a.seed, since=after)
            written = ba.write(got, out)
            note(f"{len(got['queue'])} rows to label ({sum(k['role'] == 'sample' for k in got['key'])} sampled, "
                 f"{sum(k['role'] == 'plant' for k in got['key'])} planted), store max verdict "
                 f"{got['header']['max_verdict_id']}, seed {a.seed}: " + ", ".join(str(p) for p in written))
            emit(True, header=got["header"], queue=[r["verdict_id"] for r in got["queue"]])
            return 0
        labels = Path(a.labels) if a.labels else out / "labels.csv"
        second = Path(a.second) if a.second else out / "labels-second.csv"
        try:
            got = ba.report(out / "key.csv", labels, second, conn)
            earlier = Path(a.against) if getattr(a, "against", "") else None
            if earlier is not None:
                got["against"] = ba.compare(got, ba.report(earlier / "key.csv", earlier / "labels.csv",
                                                           earlier / "labels-second.csv"))
        except (OSError, ValueError, KeyError) as exc:
            return err(f"blame report: {exc}")
    finally:
        conn.close()
    note(ba.report_text(got) + (f"\n{ba.compare_text(got['against'])}" if "against" in got else ""))
    emit(True, **got)
    return 0
