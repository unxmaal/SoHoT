"""Schema 106: verdicts.sized_by, and event, failure_class and reopen_kind lifted once from older rows' detail. #1942."""
from __future__ import annotations

import re

from harness.memory_store.schema import _columns

VERSION = 106

# The words each writer said before #1942, frozen here so a later rewording cannot change this step.
_INSPECT_WORDS = ("fits", "too-big", "no-entry-point", "dead", "unknown", "weights-in-git")
_MARK = "smallest variant "
_FUTILITY = re.compile(r"^(?:[\w.-]+:\s*)?futility:|confirmation stopped for futility:")
_INCOMPLETE = re.compile(r"cached snapshot .{0,400}? is incomplete: \d+ file\(s\) are missing")


def columns(conn) -> None:
    if "sized_by" not in _columns(conn, "verdicts"):
        conn.execute("ALTER TABLE verdicts ADD COLUMN sized_by TEXT NOT NULL DEFAULT ''")


def data(conn) -> None:
    for word in _INSPECT_WORDS:
        conn.execute("UPDATE verdicts SET event = ? WHERE tier = 'inspect' AND event = '' "
                     "AND (detail = ? OR substr(detail, 1, ?) = ?)", (word, word, len(word) + 1, f"{word}:"))
    for r in conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'inspect' AND event = '' "
                          "AND detail LIKE 'needs-%'").fetchall():
        conn.execute("UPDATE verdicts SET event = ? WHERE id = ?", (r["detail"].partition(":")[0].strip(), r["id"]))
    for sized, like in (("gguf", f"%{_MARK}%.gguf%"), ("variant", f"%{_MARK}%"),
                        ("resident", "too-big:%GiB resident%"), ("listing", "too-big:%")):
        conn.execute("UPDATE verdicts SET sized_by = ? WHERE tier = 'inspect' AND sized_by = '' AND detail LIKE ?",
                     (sized, like))
    for r in conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'adopt' AND event = ''").fetchall():
        d = r["detail"] or ""
        event = ("worse" if "significantly worse" in d else "futility" if _FUTILITY.search(d)
                 else "baseline" if "taken from measurement" in d else "")
        if event:
            conn.execute("UPDATE verdicts SET event = ? WHERE id = ?", (event, r["id"]))
    for r in conn.execute("SELECT id, detail FROM verdicts WHERE tier = 'screen' AND failure_class != 'incomplete_copy' "
                          "AND detail LIKE '%is incomplete:%'").fetchall():
        if _INCOMPLETE.search((r["detail"] or "").lower()):
            conn.execute("UPDATE verdicts SET failure_class = 'incomplete_copy' WHERE id = ?", (r["id"],))
    conn.execute("UPDATE verdicts SET reopen_kind = 'retraction' WHERE reopen_kind = '' "
                 "AND substr(detail, 1, 10) = 'retracted:'")
